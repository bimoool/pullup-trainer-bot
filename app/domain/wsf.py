"""Разряды WSF (World Streetlifting Federation) по многоповторным
подтягиваниям с отягощением (issue #104) — вторая система оценки в
профиле, ДОПОЛНЯЮЩАЯ ГТО (app.domain.gto), не заменяющая его. В отличие от
ГТО (только мужчины — официальный женский норматив ГТО измеряет другое
упражнение, вис лёжа), дисциплина WSF "многоповторные" одна и та же для
обоих полов — здесь нет ограничения по полу.

Источник данных — app/domain/data/wsf_multirep_norms.json (официальные PDF
WSF, распарсенные автором продукта и закоммиченные как чистые данные,
коммит 7fa0f60 issue #104 — не выдуманы). Только дисциплина "многоповторные"
(фиксированное отягощение, повторения на максимум) — дисциплина "на
максимум" (однократный предельный вес) сознательно не подключена: наша
модель данных никогда не собирает однократный тест на 1ПМ, только рабочие
подходы на повторения (обсуждено и подтверждено в issue #104).

Три развилки, подтверждённые автором продукта в issue #104 (не додуманы):
- допинг-контроль: всегда "non_tested" (без ДК, ближе к реальности
  любительского приложения) — "doping_tested" из файла не используется;
- весовая категория пользователя: округление ВВЕРХ — минимальная категория
  ИЗ таблицы, которая ≥ фактического веса пользователя (как в классическом
  пауэрлифтинге);
- ступень отягощения тренировки: округление ВНИЗ — ближайшая ступень ИЗ
  таблицы [0,10,15,25,35,50], которая ≤ фактического отягощения тренировки.
  Округление вниз ЗАНИЖАЕТ фактический результат при сравнении (пользователь
  поднял 23 кг, а норматив сверяется по ступени 15 кг) — по прямому
  требованию автора продукта вызывающая сторона (веб/бот) ОБЯЗАНА явно
  показать пользователю и реальный вес, и ступень, по которой считался
  норматив (см. WsfStatus.actual_added_weight_kg отдельно от
  added_weight_step_kg) — не молчаливое несовпадение цифр в интерфейсе.

Возрастной бонус (meta.age_bonus в JSON, однозначно описан в самих
таблицах — отдельного подтверждения не требовалось) — процентная надбавка к
реально выполненным повторениям перед сравнением с порогами (50-54: +10%
… 70+: +30%), результат округляется ВНИЗ до целого повторения (правило из
PDF-таблиц). reps_to_next_rank в статусе — количество РЕАЛЬНЫХ (без бонуса)
повторений, которых не хватает до следующего разряда, а не порог "в
пространстве с бонусом" — иначе цифра не соответствовала бы тому, что
пользователь физически должен сделать на тренировке.

Как и app.domain.gto.calculate_gto_status, статус пересчитывается на лету
при каждом запросе и обратим в обе стороны (возраст сменил бонусную
ступень, вес сменил весовую категорию) — ничего не пишется в БД. Берётся
ЛУЧШИЙ разряд, достигнутый хоть раз за всю историю блока Б среди тренировок,
сопоставимых с таблицей (см. _is_wsf_eligible) — та же семантика "лучший
результат за всю историю", что best_max_reps у ГТО, только здесь оценивается
не число повторений напрямую, а достигнутый РАЗРЯД (у разных тренировок
могут быть разные ступени отягощения, поэтому напрямую сравнивать
повторения между тренировками бессмысленно — сравниваются только разряды)."""

import json
import math
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from app.domain.constants import EquipmentType
from app.domain.session import BlockAssignment, WorkoutRecord

# "male"/"female" — те же значения, что app.db.models.Gender, переданные
# вызывающей стороной как строка (не сам enum) — тот же принцип, что MALE в
# app.domain.gto: app/domain/ не импортирует app.db.models (тянет sqlalchemy).
MALE = "male"
FEMALE = "female"

# JSON-файл использует "men"/"women" (как в самих PDF-таблицах WSF), не
# "male"/"female" (значения app.db.models.Gender) — единственное место
# преобразования между двумя словарями, чтобы не размазывать его по всем
# функциям, которые индексируются в _NORMS/_CATEGORIES.
_GENDER_KEY: dict[str, str] = {MALE: "men", FEMALE: "women"}

_DATA_PATH = Path(__file__).parent / "data" / "wsf_multirep_norms.json"
_DATA = json.loads(_DATA_PATH.read_text())
_NORMS = _DATA["multirep"]["non_tested"]  # doping_tested не используется, см. докстринг модуля
_RANKS: tuple[str, ...] = tuple(_DATA["meta"]["ranks"])  # ("elite",...,"iii") — лучший → худший
_WEIGHT_LADDER: tuple[int, ...] = tuple(sorted(int(x) for x in _DATA["meta"]["weight_brackets_kg"]))
_AGE_BONUS: dict[tuple[int, int | None], Decimal] = {
    (50, 54): Decimal("0.1"),
    (55, 59): Decimal("0.15"),
    (60, 64): Decimal("0.2"),
    (65, 69): Decimal("0.25"),
    (70, None): Decimal("0.3"),
}
# Дублирует meta.age_bonus того же JSON как Decimal-константы — та же
# причина, что у остальных числовых порогов домена (app/domain/constants.py):
# точное сравнение десятичных долей, не float.

_EQUIPMENT_TYPES_ELIGIBLE = (EquipmentType.WEIGHT, EquipmentType.BODYWEIGHT)
# Та же пара типов, что _EPLEY_ELIGIBLE_TYPES в app.domain.reports (issue
# #96) — резина/австралийские отжимания не выражают отягощение в кг, не
# сопоставимы с таблицей WSF (тот же принцип: "резина принципиально не
# приводится к общей шкале нагрузки").


def _category_keys(gender: str) -> tuple[tuple[Decimal, str], ...]:
    """Весовые категории конкретного пола по возрастанию, БЕЗ открытой
    категории "999" (она — фолбэк за пределами последней границы, см.
    _resolve_category_key). Ступень отягощения "0" выбрана источником
    категорий, потому что для неё данные женщин заполнены полностью (в
    отличие от 25/35/50, см. докстринг модуля) — набор категорий одинаков на
    всех ступенях отягощения одного пола."""
    gender_key = _GENDER_KEY[gender]
    return tuple(
        sorted(
            ((Decimal(key), key) for key in _NORMS["0"][gender_key] if key != "999"),
            key=lambda pair: pair[0],
        ),
    )


_CATEGORIES: dict[str, tuple[tuple[Decimal, str], ...]] = {
    MALE: _category_keys(MALE),
    FEMALE: _category_keys(FEMALE),
}


class WsfRank:
    """Не StrEnum (как GtoRank) — значения читаются прямо из meta.ranks
    JSON-файла, а не фиксируются в коде: если WSF когда-нибудь дополнит
    таблицу новым разрядом, достаточно поправить только JSON."""

    NONE = "none"


def calculate_age(birth_date: date, today: date) -> int:
    """Копия app.domain.gto.calculate_age/app.domain.leaderboard.age_bucket/
    app.bot.formatting.calculate_age — та же причина не импортировать между
    модулями домена, что уже объяснена в докстринге app.domain.gto: расчёт
    короче, чем абстракция вокруг него, а app/domain/ не зависит от app/bot/."""
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


@dataclass(frozen=True)
class WsfRankThreshold:
    rank: str
    reps: int


@dataclass(frozen=True)
class WsfStatus:
    """applicable=False — reason объясняет причину (используется фронтендом
    для текста, не только для ветвления):
    "missing_gender" — пол не указан в профиле;
    "missing_weight" — вес не указан в профиле;
    "no_workouts" — ни одной тренировки блока Б на WEIGHT/BODYWEIGHT с
    зафиксированным максимумом (см. _is_wsf_eligible);
    "norm_data_missing" — все подходящие тренировки попали в ступень
    отягощения, для которой у этого пола нет данных вовсе (женщины на
    25/35/50 кг добавленного веса, см. докстринг модуля) — gender/
    weight_category всё равно заполнены (тот же приём, что age/step_number
    у GtoStatus при norm_data_missing).

    added_weight_step_kg — ступень ИЗ таблицы [0,10,15,25,35,50], по которой
    ФАКТИЧЕСКИ считался разряд (округление ВНИЗ). actual_added_weight_kg —
    реальный вес отягощения той тренировки, что дала лучший разряд — может
    не совпадать со ступенью (интерфейс обязан показать оба числа, см.
    докстринг модуля). age_bonus_pct — None, если бонус не применялся
    (моложе 50 лет или не указана дата рождения в профиле)."""

    applicable: bool
    reason: str | None = None
    gender: str | None = None
    weight_category: str | None = None
    rank: str | None = None
    best_reps: int | None = None
    added_weight_step_kg: Decimal | None = None
    actual_added_weight_kg: Decimal | None = None
    age_bonus_pct: Decimal | None = None
    next_rank: str | None = None
    reps_to_next_rank: int | None = None
    thresholds: tuple[WsfRankThreshold, ...] = ()


def _resolve_age_bonus(age: int | None) -> Decimal | None:
    if age is None:
        return None
    for (min_age, max_age), bonus in _AGE_BONUS.items():
        if age >= min_age and (max_age is None or age <= max_age):
            return bonus
    return None


def _resolve_category_key(weight_kg: Decimal, gender: str) -> str:
    for threshold, key in _CATEGORIES[gender]:
        if weight_kg <= threshold:
            return key
    return "999"


def _resolve_weight_step(equipment_value_kg: Decimal) -> int:
    step = _WEIGHT_LADDER[0]
    for candidate in _WEIGHT_LADDER:
        if equipment_value_kg >= candidate:
            step = candidate
        else:
            break
    return step


def _is_wsf_eligible(block: BlockAssignment) -> bool:
    """Тот же критерий, что _epley_eligible (issue #96): только WEIGHT/
    BODYWEIGHT (резина/AUSTRALIAN не выражают кг), best_set > 0 отсекает
    бэкдейт-итог без зафиксированного максимума (issue #88)."""
    return block.equipment_type in _EQUIPMENT_TYPES_ELIGIBLE and block.log.best_set > 0


def _actual_added_weight(block: BlockAssignment) -> Decimal:
    if block.equipment_type != EquipmentType.WEIGHT:
        return Decimal(0)
    return block.equipment_value or Decimal(0)


def _adjusted_reps(reps: int, bonus: Decimal | None) -> int:
    if bonus is None:
        return reps
    return math.floor(Decimal(reps) * (Decimal(1) + bonus))


def _resolve_rank(adjusted_reps: int, thresholds: list[int | None]) -> str:
    for rank_value, threshold in zip(_RANKS, thresholds, strict=True):
        if threshold is not None and adjusted_reps >= threshold:
            return rank_value
    return WsfRank.NONE


def _next_rank(rank: str, thresholds: list[int | None]) -> tuple[str, int] | None:
    achieved_index = len(_RANKS) if rank == WsfRank.NONE else _RANKS.index(rank)
    for index in range(achieved_index - 1, -1, -1):
        threshold = thresholds[index]
        if threshold is not None:
            return _RANKS[index], threshold
    return None


def _reps_needed_for_threshold(threshold: int, bonus: Decimal | None) -> int:
    """Реальные (без бонуса) повторения, необходимые, чтобы после
    возрастного бонуса (округление ВНИЗ) результат достиг порога — не сам
    порог напрямую, если бонус применяется, иначе цифра "не хватает N
    повторений" оказалась бы в пространстве "с бонусом", а не тех живых
    повторений, которые пользователь физически делает на тренировке."""
    if bonus is None:
        return threshold
    needed = Decimal(threshold) / (Decimal(1) + bonus)
    return int(needed.to_integral_value(rounding=ROUND_CEILING))


# _RANKS упорядочен от лучшего (elite, индекс 0) к худшему (iii, индекс
# len-1) — для сравнения "какой разряд лучше" нужен обратный счёт: iii=0
# (худший определённый разряд) ... elite=len-1 (лучший). WsfRank.NONE (хуже
# iii) обрабатывается отдельно как -1, без записи в словарь.
_RANK_SCORE: dict[str, int] = {
    rank_value: index for index, rank_value in enumerate(reversed(_RANKS))
}


def _rank_score(rank: str) -> int:
    return -1 if rank == WsfRank.NONE else _RANK_SCORE[rank]


@dataclass(frozen=True)
class _Candidate:
    rank: str
    reps: int
    added_weight_step_kg: Decimal
    actual_added_weight_kg: Decimal
    thresholds: list[int | None]


def calculate_wsf_status(
    *,
    gender: str | None,
    weight_kg: Decimal | None,
    birth_date: date | None,
    records: list[WorkoutRecord],
    today: date,
) -> WsfStatus:
    if gender not in (MALE, FEMALE):
        return WsfStatus(applicable=False, reason="missing_gender")
    if weight_kg is None:
        return WsfStatus(applicable=False, reason="missing_weight")

    category_key = _resolve_category_key(weight_kg, gender)
    age = calculate_age(birth_date, today) if birth_date is not None else None
    bonus = _resolve_age_bonus(age)

    eligible = [r.block_b for r in records if _is_wsf_eligible(r.block_b)]
    if not eligible:
        return WsfStatus(
            applicable=False, reason="no_workouts", gender=gender, weight_category=category_key,
        )

    gender_key = _GENDER_KEY[gender]
    best: _Candidate | None = None
    norm_data_seen = False
    for block in eligible:
        actual_value = _actual_added_weight(block)
        step = _resolve_weight_step(actual_value)
        gender_norms = _NORMS[str(step)].get(gender_key)
        if gender_norms is None:
            continue
        norm_data_seen = True
        # JSON хранит повторения как float (56.0) — приводим к int сразу
        # после чтения, единственный источник конвертации, чтобы дальше по
        # цепочке (сравнение, reps_to_next_rank, WsfRankThreshold.reps) не
        # плавали дробные "56.0" вместо целых повторений.
        thresholds = [None if t is None else int(t) for t in gender_norms[category_key]]
        reps = block.log.best_set
        rank = _resolve_rank(_adjusted_reps(reps, bonus), thresholds)
        # >= (не >) — при равном разряде побеждает более позднее вхождение:
        # eligible хронологически по возрастанию (см. WorkoutRepository.
        # list_for_user), поэтому статус тяготеет к недавнему результату.
        if best is None or _rank_score(rank) >= _rank_score(best.rank):
            best = _Candidate(
                rank=rank, reps=reps, added_weight_step_kg=Decimal(step),
                actual_added_weight_kg=actual_value, thresholds=thresholds,
            )

    if not norm_data_seen:
        return WsfStatus(
            applicable=False, reason="norm_data_missing",
            gender=gender, weight_category=category_key,
        )

    assert best is not None  # norm_data_seen=True гарантирует хотя бы одного best

    next_rank, reps_to_next = None, None
    next_ = _next_rank(best.rank, best.thresholds)
    if next_ is not None:
        next_rank, threshold = next_
        needed = _reps_needed_for_threshold(threshold, bonus)
        reps_to_next = max(needed - best.reps, 0)

    thresholds_out = tuple(
        WsfRankThreshold(rank=rank_value, reps=threshold)
        for rank_value, threshold in zip(_RANKS, best.thresholds, strict=True)
        if threshold is not None
    )

    return WsfStatus(
        applicable=True,
        reason=None,
        gender=gender,
        weight_category=category_key,
        rank=best.rank,
        best_reps=best.reps,
        added_weight_step_kg=best.added_weight_step_kg,
        actual_added_weight_kg=best.actual_added_weight_kg,
        age_bonus_pct=bonus,
        next_rank=next_rank,
        reps_to_next_rank=reps_to_next,
        thresholds=thresholds_out,
    )
