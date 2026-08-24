from datetime import UTC, datetime, timedelta

from app.db.repositories.weekly_digests import WeeklyDigestRepository


async def test_get_last_sent_at_none_when_empty(session):
    assert await WeeklyDigestRepository(session).get_last_sent_at() is None


async def test_record_stores_digest_and_get_last_sent_at_returns_most_recent(session):
    repo = WeeklyDigestRepository(session)
    first_sent_at = datetime(2026, 1, 5, 18, tzinfo=UTC)
    second_sent_at = first_sent_at + timedelta(days=7)

    await repo.record(sent_at=first_sent_at, text="Первый дайджест", recipients_count=10)
    digest = await repo.record(sent_at=second_sent_at, text="Второй дайджест", recipients_count=12)

    assert digest.text == "Второй дайджест"
    assert digest.recipients_count == 12
    assert await repo.get_last_sent_at() == second_sent_at


async def test_get_last_sent_at_ignores_insertion_order_uses_sent_at(session):
    """Порядок вставки не гарантирует порядок sent_at (например, если
    строку восстанавливают/бэкфиллят) — источник истины именно sent_at,
    не id/порядок записи."""
    repo = WeeklyDigestRepository(session)
    later = datetime(2026, 2, 1, 18, tzinfo=UTC)
    earlier = datetime(2026, 1, 1, 18, tzinfo=UTC)

    await repo.record(sent_at=later, text="Позже по дате, записан первым", recipients_count=5)
    await repo.record(sent_at=earlier, text="Раньше по дате, записан вторым", recipients_count=5)

    assert await repo.get_last_sent_at() == later
