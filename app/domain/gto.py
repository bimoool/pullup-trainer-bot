"""Разряды ГТО по подтягиванию (issue #71) — отдельная концепция, не часть
`app.domain.achievements`/`AchievementRepository`: это не разовая веха
("получил и навсегда"), а текущий статус — сравнение лучшего результата
пользователя с официальным нормативом ВФСК ГТО для его пола/возрастной
ступени, обратимый в обе стороны (результат снизился — разряд может быть
уже не подтверждён; пользователь перешёл в новую возрастную ступень —
поменялся сам норматив). Поэтому здесь только чистый расчёт "на лету" по
текущим данным, ничего не пишется в БД (см. app/web/routes.py::get_gto).

Только мужчины: официальный женский норматив ГТО по подтягиванию измеряет
другое упражнение (вис ЛЁЖА на низкой перекладине, не вис на высокой, как
у мужчин и как тренирует это приложение) — цифры несравнимы напрямую, не
взята придуманная шкала для женщин (issue #71, обсуждение).

Возрастная сетка — 12 официальных ступеней ГТО для взрослых (7-я: 18-19
лет … 18-я: 70+), НЕ переиспользует укрупнённую 6-диапазонную
app.domain.leaderboard.AGE_BUCKETS (issue #67) — та достаточна для
лидерборда как приблизительная категория, но не подходит для точного
присвоения разряда. calculate_age здесь — та же арифметика, что
app.domain.leaderboard.age_bucket и app.bot.formatting.calculate_age,
продублированная явно по той же причине (app/domain/ не зависит от
app/bot/, а расчёт короткий).

Источник нормативов — официальные таблицы gto.ru/normativy/muzhchiny/
{N}-stupen-{возраст}-let/ (подтягивание из виса на высокой перекладине,
мужчины), собраны вручную автором issue #71 постранично, не выдуманы:
7 ст.(18-19) 15/12/8, 8 ст.(20-24) 16/13/9, 9 ст.(25-29) 14/10/6,
10 ст.(30-34) 13/8/4, 11 ст.(35-39) 11/7/4, 12 ст.(40-44) 10/7/3,
13 ст.(45-49) 9/6/2, 15 ст.(55-59) 7/4/2 (золото/серебро/бронза).

14 ст.(50-54) не подтверждена с первоисточника (веб-доступ был недоступен
в сессии реализации) — использована линейная интерполяция между
подтверждёнными соседями (13 ст. и 15 ст., обе стороны известны), с явной
пометкой ниже: золото 8, серебро 5, бронза 2.

16/17/18 ступени (60-64, 65-69, 70+) не заполнены вовсе, не
интерполированы: у них нет второго известного соседа (18-я — последняя
ступень, без верхней границы) — интерполяция "в один конец" была бы уже
не разумной оценкой, а угадыванием числа. bronze/silver/gold=None здесь
означает "норматив для этой ступени ещё не подтверждён с первоисточника",
не "0 подтягиваний" — calculate_gto_status возвращает отдельную причину
недоступности (norm_data_missing), которую фронтенд должен показать
честно, не молчаливым нулём."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

# "male"/"female" — те же значения, что app.db.models.Gender, переданные
# вызывающей стороной как строка (не сам enum): app/domain/ не должен
# импортировать app.db.models (тянет sqlalchemy), тот же принцип, что и у
# остального домена (EquipmentType — своя копия в app.domain.constants, не
# импорт ORM-enum).
MALE = "male"


class GtoRank(StrEnum):
    NONE = "none"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


@dataclass(frozen=True)
class GtoAgeStep:
    number: int
    min_age: int
    max_age: int | None  # None — без верхней границы (18-я ступень, 70+)
    bronze: int | None
    silver: int | None
    gold: int | None


GTO_MALE_PULLUP_STEPS: tuple[GtoAgeStep, ...] = (
    GtoAgeStep(number=7, min_age=18, max_age=19, bronze=8, silver=12, gold=15),
    GtoAgeStep(number=8, min_age=20, max_age=24, bronze=9, silver=13, gold=16),
    GtoAgeStep(number=9, min_age=25, max_age=29, bronze=6, silver=10, gold=14),
    GtoAgeStep(number=10, min_age=30, max_age=34, bronze=4, silver=8, gold=13),
    GtoAgeStep(number=11, min_age=35, max_age=39, bronze=4, silver=7, gold=11),
    GtoAgeStep(number=12, min_age=40, max_age=44, bronze=3, silver=7, gold=10),
    GtoAgeStep(number=13, min_age=45, max_age=49, bronze=2, silver=6, gold=9),
    # Интерполировано между 13 и 15 ступенями (см. докстринг модуля) —
    # не подтверждено напрямую с gto.ru.
    GtoAgeStep(number=14, min_age=50, max_age=54, bronze=2, silver=5, gold=8),
    GtoAgeStep(number=15, min_age=55, max_age=59, bronze=2, silver=4, gold=7),
    # Нормативы ещё не собраны (нет второго известного соседа для
    # интерполяции) — bronze/silver/gold=None, см. докстринг модуля.
    GtoAgeStep(number=16, min_age=60, max_age=64, bronze=None, silver=None, gold=None),
    GtoAgeStep(number=17, min_age=65, max_age=69, bronze=None, silver=None, gold=None),
    GtoAgeStep(number=18, min_age=70, max_age=None, bronze=None, silver=None, gold=None),
)


@dataclass(frozen=True)
class GtoStatus:
    """applicable=False — статус не может быть посчитан, reason объясняет
    почему (используется фронтендом для текста, не только для ветвления):
    "only_male" — пол не "male" (женский норматив измеряет другое упражнение,
    см. докстринг модуля; пол ещё не указан в профиле — та же причина, без
    отдельного кода: сообщение пользователю одинаковое в обоих случаях);
    "missing_birth_date" — дата рождения не заполнена в профиле;
    "age_out_of_range" — младше 18 (взрослой сетки ГТО для него нет);
    "norm_data_missing" — попал в возрастную ступень, для которой числа
    ещё не подтверждены (16-18); "no_workouts" — ещё нет ни одной
    тренировки, best_max_reps посчитать не из чего. Отдельно, но тем же
    полем reason — "not_onboarded" (не значение этой функции: подставляется
    в app/web/routes.py::get_gto до вызова, когда пользователя ещё нет в
    БД вообще — этой функции нечего было бы проверять).

    step/bronze_threshold/silver_threshold/gold_threshold заполнены только
    когда applicable=True. next_rank/reps_to_next_rank — None у GOLD (уже
    максимальный разряд)."""

    applicable: bool
    reason: str | None
    age: int | None = None
    step_number: int | None = None
    rank: GtoRank | None = None
    best_max_reps: int | None = None
    bronze_threshold: int | None = None
    silver_threshold: int | None = None
    gold_threshold: int | None = None
    next_rank: GtoRank | None = None
    reps_to_next_rank: int | None = None


def calculate_age(birth_date: date, today: date) -> int:
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def resolve_gto_age_step(age: int) -> GtoAgeStep | None:
    for step in GTO_MALE_PULLUP_STEPS:
        if age < step.min_age:
            continue
        if step.max_age is None or age <= step.max_age:
            return step
    return None


def calculate_gto_status(
    *,
    gender: str | None,
    birth_date: date | None,
    best_max_reps: int | None,
    today: date,
) -> GtoStatus:
    if gender != MALE:
        return GtoStatus(applicable=False, reason="only_male")
    if birth_date is None:
        return GtoStatus(applicable=False, reason="missing_birth_date")

    age = calculate_age(birth_date, today)
    step = resolve_gto_age_step(age)
    if step is None:
        return GtoStatus(applicable=False, reason="age_out_of_range", age=age)
    if step.gold is None:
        return GtoStatus(applicable=False, reason="norm_data_missing", age=age, step_number=step.number)
    if best_max_reps is None:
        return GtoStatus(
            applicable=False, reason="no_workouts", age=age, step_number=step.number,
        )

    if best_max_reps >= step.gold:
        rank = GtoRank.GOLD
        next_rank, reps_to_next = None, None
    elif best_max_reps >= step.silver:
        rank = GtoRank.SILVER
        next_rank, reps_to_next = GtoRank.GOLD, step.gold - best_max_reps
    elif best_max_reps >= step.bronze:
        rank = GtoRank.BRONZE
        next_rank, reps_to_next = GtoRank.SILVER, step.silver - best_max_reps
    else:
        rank = GtoRank.NONE
        next_rank, reps_to_next = GtoRank.BRONZE, step.bronze - best_max_reps

    return GtoStatus(
        applicable=True,
        reason=None,
        age=age,
        step_number=step.number,
        rank=rank,
        best_max_reps=best_max_reps,
        bronze_threshold=step.bronze,
        silver_threshold=step.silver,
        gold_threshold=step.gold,
        next_rank=next_rank,
        reps_to_next_rank=reps_to_next,
    )
