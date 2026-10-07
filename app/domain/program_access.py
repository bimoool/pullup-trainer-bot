"""Доступ к тренировкам программы (курса) — продуктовое правило владельца 2026-10-07.

Две независимые оси, не смешивать:
  * entitlement (users.subscription_*, SubscriptionService.entitled) — есть ли у пользователя Premium
    (пробный период или оплаченная/выданная подписка);
  * access level программы (programs.access_level) — нужна ли Premium вообще, чтобы тренироваться по ней.

Бесплатная программа (FREE) доступна всегда и всем, независимо от подписки: её не «делают бесплатной»
бесконечной подпиской и не отмечают пользователя Premium навсегда. Единственная такая программа сейчас —
системная «Подтягивания» (бесплатна навсегда: добавить в план, стартовать, завершать, повторять, история).
Всё, что явно не FREE, — PREMIUM (как было до правила, D6/#300).

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


def program_training_allowed(access_level: ProgramAccessLevel | str | None, *, entitled: bool) -> bool:
    """ЕДИНСТВЕННОЕ решение «можно ли стартовать/записать тренировку по программе». FREE — всегда; всё остальное
    (PREMIUM и неизвестное/пустое значение — fail closed) — только при действующем entitlement."""
    if access_level is not None and ProgramAccessLevel(access_level) is ProgramAccessLevel.FREE:
        return True
    return entitled


def programs_training_allowed(access_levels: list[ProgramAccessLevel | str | None], *, entitled: bool) -> bool:
    """Тренировка из строк нескольких программ разрешена, только если разрешена каждая (смешанный запрос с
    платной программой без подписки отклоняется целиком, как и раньше)."""
    return all(program_training_allowed(level, entitled=entitled) for level in access_levels)
