from datetime import UTC, datetime

from app.db.models import User
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.events import EventRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.services.elective_log import ElectiveLogService


async def test_record_creates_elective_and_event(session, user: User):
    service = ElectiveLogService(session)

    elective = await service.record(
        user_id=user.id, elective_type=ElectiveType.THREE_MINUTES, performed_at=datetime.now(UTC),
        total_reps=42, reps_sequence=[10, 9, 8, 7, 5, 3], equipment_type=EquipmentType.BODYWEIGHT,
    )

    assert elective.total_reps == 42
    assert elective.reps_sequence == [10, 9, 8, 7, 5, 3]

    [event] = await EventRepository(session).list_for_user(user.id)
    assert event.event_type == "elective_completed"
    assert event.payload == {"elective_type": "three_minutes", "volume": 42}


async def test_record_volume_target_event_payload(session, user: User):
    service = ElectiveLogService(session)

    await service.record(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=datetime.now(UTC),
        total_reps=52, reps_sequence=None, equipment_type=EquipmentType.BAND,
    )

    [event] = await EventRepository(session).list_for_user(user.id)
    assert event.payload == {"elective_type": "volume_target", "volume": 52}


async def test_record_checks_volume_milestones(session, user: User):
    service = ElectiveLogService(session)

    await service.record(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=datetime.now(UTC),
        total_reps=150, reps_sequence=None, equipment_type=EquipmentType.BODYWEIGHT,
    )

    assert await AchievementRepository(session).has_unlocked(user.id, "volume_100") is True


async def test_record_does_not_unlock_volume_milestone_below_threshold(session, user: User):
    service = ElectiveLogService(session)

    await service.record(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=datetime.now(UTC),
        total_reps=50, reps_sequence=None, equipment_type=EquipmentType.BODYWEIGHT,
    )

    assert await AchievementRepository(session).has_unlocked(user.id, "volume_100") is False
