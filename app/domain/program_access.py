"""Доступ к тренировкам программы (курса) — продуктовое правило владельца 2026-10-07, матрица — 2026-10-17.

Две независимые оси, не смешивать:
  * entitlement (users.subscription_*, SubscriptionService.entitled) — есть ли у пользователя Premium
    (пробный период или оплаченная/выданная подписка);
  * access level программы (programs.access_level) — нужна ли Premium вообще, чтобы тренироваться по ней.

Бесплатная программа (FREE) доступна всегда и всем, независимо от подписки: её не «делают бесплатной»
бесконечной подпиской и не отмечают пользователя Premium навсегда. Единственная такая программа сейчас —
системная «Подтягивания» (бесплатна навсегда: добавить в план, стартовать, завершать, повторять, история).
Всё, что явно не FREE, — PREMIUM (как было до правила, D6/#300).

Решение владельца 2026-10-17 (PROJECT_SPEC «Подписка и доступ к курсам»): бесплатна ТОЛЬКО программа
«Подтягивания» со всем, что нужно для её прохождения. Всё остальное, что даёт новую тренировочную нагрузку или свой
контент, — Premium: произвольные дополнительные занятия (свои и готовые тренировки вне курса, свободные
подтягивания, свободная активность, ручная запись и «Повторить» в Журнале), другие программы, свои
упражнения/тренировки/планы и добавление их в план, экспорт истории. Факультативы, предусмотренные программой
«Подтягивания» (app/domain/electives.py), — часть бесплатной программы (уточнение владельца 2026-10-17). Такая часть тренировки не принадлежит бесплатной программе —
её уровень EXTRA_TRAINING_ACCESS_LEVEL (PREMIUM), решение о ней — тот же program_training_allowed. Смешанный старт
(занятие «Подтягиваний» + доп. строка) без подписки отклоняется целиком. Просмотр, история и удаление своего не
гейтятся; уже начатая тренировка завершается без проверки (гейт — только у старта/записи нового).

Чистая логика: без БД/aiogram и без datetime.now() — решение об entitlement приходит снаружи."""

from enum import StrEnum


class ProgramAccessLevel(StrEnum):
    FREE = "free"
    PREMIUM = "premium"


# Значение по умолчанию для новой программы: только явно помеченное бесплатное освобождено от подписки.
DEFAULT_PROGRAM_ACCESS_LEVEL = ProgramAccessLevel.PREMIUM

# Legacy-каскад подтягиваний (бот «💪 Начать тренировку», старые /api/workout/plan и /api/workout/backdate/plan)
# — это дореформенная реализация той же системной программы «Подтягивания» (backfill #163 переносит его историю
# в неё). Своей строки Program у него нет, поэтому уровень доступа задан здесь, один раз, и совпадает с уровнем
# этой программы.
LEGACY_PULLUP_CASCADE_ACCESS_LEVEL = ProgramAccessLevel.FREE

# Уровень части тренировки/контента, которая НЕ является занятием бесплатной программы (решение 2026-10-17):
# доп./свободная тренировка, своё упражнение/тренировка/план, строка плана без программы.
EXTRA_TRAINING_ACCESS_LEVEL = ProgramAccessLevel.PREMIUM


def program_training_allowed(access_level: ProgramAccessLevel | str | None, *, entitled: bool) -> bool:
    """ЕДИНСТВЕННОЕ решение «можно ли стартовать/записать тренировку по программе». FREE — всегда; всё остальное
    (PREMIUM и неизвестное/пустое значение — fail closed) — только при действующем entitlement."""
    if access_level is not None and ProgramAccessLevel(access_level) is ProgramAccessLevel.FREE:
        return True
    return entitled


def programs_training_allowed(access_levels: list[ProgramAccessLevel | str | None], *, entitled: bool) -> bool:
    """Тренировка из строк нескольких программ разрешена, только если разрешена каждая (смешанный запрос с
    платной программой или доп. строкой без подписки отклоняется целиком)."""
    return all(program_training_allowed(level, entitled=entitled) for level in access_levels)


def premium_feature_allowed(*, entitled: bool) -> bool:
    """Premium-функция вне бесплатной программы (доп. тренировка, свой контент, добавление в план, экспорт) —
    то же решение, что для части тренировки уровня EXTRA_TRAINING_ACCESS_LEVEL."""
    return program_training_allowed(EXTRA_TRAINING_ACCESS_LEVEL, entitled=entitled)


def _ids(values) -> frozenset[int]:
    return frozenset(int(value) for value in values if isinstance(value, int) and not isinstance(value, bool))


def free_inclusion_content(snapshot: dict | None) -> tuple[frozenset[int], frozenset[int]]:
    """(exercise_ids, complex_ids) — что предписывает ЗАМОРОЖЕННЫЙ снимок инклюзии: роли курса (`exercises`),
    строки программы (`program_items`) и участники/тренировки слотов (`slots`). Только это — «занятие бесплатной
    программы»; всё прочее в той же записи — доп. часть (решение 2026-10-17)."""
    snapshot = snapshot or {}
    exercises = [item.get("exercise_id") for item in snapshot.get("exercises") or [] if isinstance(item, dict)]
    complexes: list = []
    for item in snapshot.get("program_items") or []:
        if isinstance(item, dict):
            exercises.append(item.get("exercise_id"))
            complexes.append(item.get("complex_id"))
    for slot in snapshot.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        complexes.append(slot.get("workout_definition_id"))
        for member in slot.get("members") or []:
            if isinstance(member, dict):
                exercises.append(member.get("exercise_id"))
                complexes.append(member.get("complex_id"))
    return _ids(exercises), _ids(complexes)


def record_within_free_inclusion(
    snapshot: dict | None, *, exercise_ids: list[int], complex_ids: list[int], workout_definition_id: int | None,
) -> bool:
    """Запись сессии «Подтягиваний» без подписки бесплатна, только если КАЖДЫЙ блок — из предписанного снимком
    инклюзии (смешанная запись с чужим упражнением/тренировкой = доп. часть = Premium, как смешанный старт)."""
    allowed_exercises, allowed_complexes = free_inclusion_content(snapshot)
    wanted_complexes = [*complex_ids, *([workout_definition_id] if workout_definition_id is not None else [])]
    return set(exercise_ids) <= allowed_exercises and set(wanted_complexes) <= allowed_complexes
