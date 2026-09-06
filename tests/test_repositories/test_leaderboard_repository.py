"""LeaderboardRepository (issue #67) — единственный репозиторий проекта на
raw SQL (sqlalchemy.text()), не ORM select() (см. докстринг в
app/db/repositories/leaderboard.py). Ожидаемые значения посчитаны вручную
ниже по каждому тесту, до запуска — тот же принцип, что и остальные тесты
проекта (CLAUDE.md: "доказать, что тест реально ловит баг")."""

from datetime import UTC, datetime
from decimal import Decimal

from app.db.models import Gender
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.leaderboard import LeaderboardRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.leaderboard import LeaderboardMetric
from app.domain.session import BlockLog


async def _make_user(session, *, telegram_id: int, gender: Gender | None = None, age: int | None = None):
    user = await UserRepository(session).create(telegram_id=telegram_id, username=f"u{telegram_id}")
    if gender is not None or age is not None:
        birth_date = None
        if age is not None:
            today = datetime.now(UTC).date()
            birth_date = today.replace(year=today.year - age)
        await UserRepository(session).update_profile(user.id, gender=gender, birth_date=birth_date)
    return user


async def _record_workout(
    session,
    user_id: int,
    *,
    block_a: BlockLog,
    block_b: BlockLog,
    block_a_equipment_type: EquipmentType = EquipmentType.BODYWEIGHT,
    block_a_equipment_value: Decimal | None = None,
    block_b_equipment_type: EquipmentType = EquipmentType.BODYWEIGHT,
    block_b_equipment_value: Decimal | None = None,
):
    baseline = await BaselineRepository(session).create(
        user_id=user_id, performed_at=datetime.now(UTC), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user_id, started_from_baseline_id=baseline.id)
    return await WorkoutRepository(session).record_workout(
        user_id=user_id,
        workout_set_id=workout_set.id,
        performed_at=datetime.now(UTC),
        block_a_reps=block_a,
        block_b_reps=block_b,
        block_a_equipment_type=block_a_equipment_type,
        block_a_equipment_value=block_a_equipment_value,
        block_b_equipment_type=block_b_equipment_type,
        block_b_equipment_value=block_b_equipment_value,
    )


async def test_max_reps_ranks_by_greatest_of_max_reps_and_working_reps(session):
    user1 = await _make_user(session, telegram_id=67001)
    user2 = await _make_user(session, telegram_id=67002)

    # user1: block A max_reps=25 (сам подход на максимум — наибольшее число
    # для этого блока: GREATEST(25, max(20,20,20)) = 25).
    await _record_workout(
        session, user1.id,
        block_a=BlockLog(working_reps=(20, 20, 20), max_reps=25),
        block_b=BlockLog(working_reps=(5, 5, 5, 5), max_reps=6),
    )
    # user2: block A рабочий подход (30) больше, чем сам max_reps (15) —
    # GREATEST(15, max(10,10,30)) = 30, значение берётся из working_reps,
    # не только из max_reps.
    await _record_workout(
        session, user2.id,
        block_a=BlockLog(working_reps=(10, 10, 30), max_reps=15),
        block_b=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
    )

    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric.MAX_REPS, gender=None, age_bucket=None, requesting_user_id=None, limit=20,
    )
    by_user = {e.user_id: e for e in entries if e.user_id in (user1.id, user2.id)}
    assert by_user[user2.id].value == 30
    assert by_user[user2.id].rank == 1
    assert by_user[user1.id].value == 25
    assert by_user[user1.id].rank == 2


async def test_total_volume_sums_all_reps_across_both_blocks(session):
    user1 = await _make_user(session, telegram_id=67003)
    user2 = await _make_user(session, telegram_id=67004)

    # user1: A = 25 + (20+20+20) = 85, B = 6 + (5*4) = 26, total = 111.
    await _record_workout(
        session, user1.id,
        block_a=BlockLog(working_reps=(20, 20, 20), max_reps=25),
        block_b=BlockLog(working_reps=(5, 5, 5, 5), max_reps=6),
    )
    # user2: A = 15 + (10+10+30) = 65, B = 4 + (3*4) = 16, total = 81.
    await _record_workout(
        session, user2.id,
        block_a=BlockLog(working_reps=(10, 10, 30), max_reps=15),
        block_b=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
    )

    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric.TOTAL_VOLUME, gender=None, age_bucket=None, requesting_user_id=None, limit=20,
    )
    by_user = {e.user_id: e for e in entries if e.user_id in (user1.id, user2.id)}
    # total_volume даёт ОБРАТНЫЙ порядок относительно max_reps выше —
    # намеренная проверка, что это действительно разные агрегаты, не один и
    # тот же расчёт под двумя именами.
    assert by_user[user1.id].value == 111
    assert by_user[user1.id].rank == 1
    assert by_user[user2.id].value == 81
    assert by_user[user2.id].rank == 2


async def test_max_weight_only_considers_weight_equipment_blocks(session):
    user = await _make_user(session, telegram_id=67005)

    # Блок A — BAND (не должен участвовать), блок Б — WEIGHT 22.5 кг.
    await _record_workout(
        session, user.id,
        block_a=BlockLog(working_reps=(10, 10, 10), max_reps=12),
        block_b=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("30.0"),
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("22.5"),
    )
    # Вторая тренировка того же пользователя — блок Б на WEIGHT 25 кг (выше).
    await _record_workout(
        session, user.id,
        block_a=BlockLog(working_reps=(10, 10, 10), max_reps=12),
        block_b=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("30.0"),
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("25.0"),
    )

    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric.MAX_WEIGHT, gender=None, age_bucket=None, requesting_user_id=None, limit=20,
    )
    entry = next(e for e in entries if e.user_id == user.id)
    assert entry.value == Decimal("25.0")


async def test_gender_filter_excludes_other_gender(session):
    male = await _make_user(session, telegram_id=67006, gender=Gender.MALE)
    female = await _make_user(session, telegram_id=67007, gender=Gender.FEMALE)
    for user in (male, female):
        await _record_workout(
            session, user.id,
            block_a=BlockLog(working_reps=(10, 10, 10), max_reps=12),
            block_b=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        )

    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric.MAX_REPS, gender="male", age_bucket=None, requesting_user_id=None, limit=20,
    )
    user_ids = {e.user_id for e in entries}
    assert male.id in user_ids
    assert female.id not in user_ids


async def test_age_bucket_filter_excludes_other_bucket(session):
    young = await _make_user(session, telegram_id=67008, age=25)
    old = await _make_user(session, telegram_id=67009, age=45)
    for user in (young, old):
        await _record_workout(
            session, user.id,
            block_a=BlockLog(working_reps=(10, 10, 10), max_reps=12),
            block_b=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        )

    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric.MAX_REPS, gender=None, age_bucket="18_29", requesting_user_id=None, limit=20,
    )
    user_ids = {e.user_id for e in entries}
    assert young.id in user_ids
    assert old.id not in user_ids


async def test_requesting_user_row_included_even_outside_top_limit(session):
    leader = await _make_user(session, telegram_id=67010)
    trailing = await _make_user(session, telegram_id=67011)
    await _record_workout(
        session, leader.id,
        block_a=BlockLog(working_reps=(20, 20, 20), max_reps=25),
        block_b=BlockLog(working_reps=(5, 5, 5, 5), max_reps=6),
    )
    await _record_workout(
        session, trailing.id,
        block_a=BlockLog(working_reps=(1, 1, 1), max_reps=1),
        block_b=BlockLog(working_reps=(1, 1, 1, 1), max_reps=1),
    )

    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric.MAX_REPS, gender=None, age_bucket=None,
        requesting_user_id=trailing.id, limit=1,
    )
    # limit=1 — trailing точно вне топа (leader выше по значению), но его
    # строка обязана присутствовать благодаря requesting_user_id.
    trailing_entries = [e for e in entries if e.user_id == trailing.id]
    assert len(trailing_entries) == 1
    assert trailing_entries[0].is_current_user is True
    assert trailing_entries[0].rank == 2

    leader_entries = [e for e in entries if e.user_id == leader.id]
    assert len(leader_entries) == 1
    assert leader_entries[0].rank == 1
    assert leader_entries[0].is_current_user is False


async def test_display_name_defaults_to_none_for_anonymous_user(session):
    user = await _make_user(session, telegram_id=67012)
    await _record_workout(
        session, user.id,
        block_a=BlockLog(working_reps=(10, 10, 10), max_reps=12),
        block_b=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
    )

    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric.MAX_REPS, gender=None, age_bucket=None, requesting_user_id=None, limit=20,
    )
    entry = next(e for e in entries if e.user_id == user.id)
    assert entry.display_name is None

    await UserRepository(session).set_leaderboard_display_name(user.id, "Крутой Перец")
    entries = await LeaderboardRepository(session).top(
        metric=LeaderboardMetric.MAX_REPS, gender=None, age_bucket=None, requesting_user_id=None, limit=20,
    )
    entry = next(e for e in entries if e.user_id == user.id)
    assert entry.display_name == "Крутой Перец"
