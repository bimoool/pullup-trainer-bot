from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import EquipmentType, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.session import BlockLog

# Чередование нечётных/чётных ("тяжёлых") тренировок блока Б (issue #97) —
# сквозной прогон через WorkoutRepository напрямую (не через WorkoutLogService
# — is_heavy/heavy_equipment_value целиком забота репозитория, сервисный слой
# их не трогает). Снаряд блока Б передаётся явно (WEIGHT с самого начала) —
# репозиторий не подбирает стартовый снаряд сам (это дело suggest_starting_
# equipment на вызывающей стороне), так что тест не обязан симулировать
# полный переход с резины/своего веса на отягощение.


async def _make_set(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )
    return workout_set.id


def _day(n: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=n)


async def _record(
    workouts: WorkoutRepository, *, user_id: int, workout_set_id: int, performed_at: datetime,
    block_b_working_reps: tuple[int, ...], block_b_max_reps: int, block_b_equipment_value: Decimal,
):
    return await workouts.record_workout(
        user_id=user_id, workout_set_id=workout_set_id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=block_b_working_reps, max_reps=block_b_max_reps),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=block_b_equipment_value,
    )


async def test_heavy_alternation_full_walkthrough(session, user: User):
    workout_set_id = await _make_set(session, user)
    workouts = WorkoutRepository(session)

    # --- Тренировка 1 (позиция 1, нечётная, обычная) --------------------------
    _, target_b_state = await workouts.resolve_next_targets(user.id)
    assert target_b_state.is_heavy is False
    assert target_b_state.target == 3  # STRENGTH_BLOCK.base_target, истории ещё нет

    workout_1 = await _record(
        workouts, user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_b_working_reps=(3, 3, 3, 3), block_b_max_reps=4, block_b_equipment_value=Decimal(20),
    )
    block_b_1 = next(b for b in workout_1.blocks if b.block_type.value == "b")
    assert block_b_1.is_heavy is False
    assert block_b_1.target_after == 4  # delta=4-3=1>0 -> step=1 -> round(3)+1=4

    # --- Тренировка 2 (позиция 2, чётная, тяжёлая) -----------------------------
    _, target_b_state = await workouts.resolve_next_targets(user.id)
    assert target_b_state.is_heavy is True
    assert target_b_state.target == 4  # унаследовано от тренировки 1, без изменений
    # 20 * (1+5/30)/(1+3/30) = 21.212... -> округление вверх до шага 0.5 -> 21.5
    assert target_b_state.heavy_equipment_value == Decimal("21.5")

    workout_2 = await _record(
        workouts, user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(2),
        block_b_working_reps=(3, 3, 3, 3), block_b_max_reps=4, block_b_equipment_value=Decimal("21.5"),
    )
    block_b_2 = next(b for b in workout_2.blocks if b.block_type.value == "b")
    assert block_b_2.is_heavy is True
    assert block_b_2.target_before == 4
    assert block_b_2.target_after == 4  # заморожена, не пересчитывается
    assert block_b_2.equipment_changed is False

    # --- Тренировка 3 (позиция 3, нечётная, обычная) ---------------------------
    _, target_b_state = await workouts.resolve_next_targets(user.id)
    assert target_b_state.is_heavy is False
    assert target_b_state.target == 4  # от тренировки 1, тяжёлая (2) не сдвинула цель
    assert target_b_state.equipment_value == Decimal(20)  # НОРМАЛЬНЫЙ вес, не 21.5 тяжёлой тренировки 2

    workout_3 = await _record(
        workouts, user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(3),
        block_b_working_reps=(4, 4, 4, 4), block_b_max_reps=5, block_b_equipment_value=Decimal(20),
    )
    block_b_3 = next(b for b in workout_3.blocks if b.block_type.value == "b")
    assert block_b_3.is_heavy is False
    assert block_b_3.target_before == 4
    assert block_b_3.target_after == 5  # delta=5-4=1>0 -> step=1 -> round(4)+1=5

    # --- Тренировка 4 (позиция 4, чётная, тяжёлая) — 5-й подход НИЖЕ порога роста
    _, target_b_state = await workouts.resolve_next_targets(user.id)
    assert target_b_state.is_heavy is True
    assert target_b_state.target == 5
    # Последняя тяжёлая (тренировка 2) имела max_reps=4 < HEAVY_GROWTH_MAX_REPS_THRESHOLD(5) -> без роста.
    assert target_b_state.heavy_equipment_value == Decimal("21.5")

    workout_4 = await _record(
        workouts, user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(4),
        block_b_working_reps=(3, 3, 3, 3), block_b_max_reps=5, block_b_equipment_value=Decimal("21.5"),
    )
    block_b_4 = next(b for b in workout_4.blocks if b.block_type.value == "b")
    assert block_b_4.is_heavy is True
    assert block_b_4.max_reps == 5  # >= порог роста -> следующая тяжёлая должна вырасти

    # --- Тренировка 5 (позиция 5, нечётная, обычная) — снаряд по-прежнему нормальный
    _, target_b_state = await workouts.resolve_next_targets(user.id)
    assert target_b_state.is_heavy is False
    assert target_b_state.equipment_value == Decimal(20)  # всё ещё нормальный вес тренировки 3, не тяжёлой 4

    workout_5 = await _record(
        workouts, user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(5),
        block_b_working_reps=(4, 4, 4, 4), block_b_max_reps=5, block_b_equipment_value=Decimal(20),
    )
    block_b_5 = next(b for b in workout_5.blocks if b.block_type.value == "b")
    assert block_b_5.is_heavy is False

    # --- Тренировка 6 (позиция 6, чётная, тяжёлая) — рост от тренировки 4 ------
    _, target_b_state = await workouts.resolve_next_targets(user.id)
    assert target_b_state.is_heavy is True
    # Триггер сработал на тренировке 4 (max_reps=5) -> 21.5 + 0.5 = 22.0, несмотря
    # на нормальную тренировку 5 между ними (найдена ПОСЛЕДНЯЯ тяжёлая, не соседняя).
    assert target_b_state.heavy_equipment_value == Decimal("22.0")


async def test_heavy_alternation_never_triggers_on_band_or_bodyweight(session, user: User):
    workout_set_id = await _make_set(session, user)
    workouts = WorkoutRepository(session)

    # Позиции 1/2/3 — BAND, BODYWEIGHT, BODYWEIGHT: до записи каждой из них
    # снаряд блока Б ещё не WEIGHT, is_heavy обязан оставаться False
    # независимо от чётности позиции (позиция 2 — чётная, самый интересный
    # кейс: без фильтра по equipment_type она бы дала is_heavy=True).
    for day, equipment_type in ((1, EquipmentType.BAND), (2, EquipmentType.BODYWEIGHT), (3, EquipmentType.BODYWEIGHT)):
        _, target_b_state = await workouts.resolve_next_targets(user.id)
        assert target_b_state.is_heavy is False
        await workouts.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(day),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
            block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
            block_b_equipment_type=equipment_type, block_b_equipment_value=None,
        )

    # Позиция 4 (чётная) — снаряд по-прежнему BODYWEIGHT (тренировка 3), не
    # WEIGHT: тот же фильтр должен продолжать держать is_heavy=False.
    _, target_b_state = await workouts.resolve_next_targets(user.id)
    assert target_b_state.is_heavy is False


async def test_backdated_workout_block_b_is_never_heavy(session, user: User):
    workout_set_id = await _make_set(session, user)
    workouts = WorkoutRepository(session)

    # Первая (обычная) тренировка на WEIGHT, чтобы следующая позиция была чётной.
    await _record(
        workouts, user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_b_working_reps=(3, 3, 3, 3), block_b_max_reps=4, block_b_equipment_value=Decimal(20),
    )

    # Бэкдейт занимает позицию 2 (чётную) в счётчике сета, но is_heavy для
    # него не считается вообще — блок Б бэкдейта целиком вне пересчёта
    # прогрессии (issue #88), чередование (issue #97) его не касается.
    workout = await workouts.record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(2),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal(20),
    )
    block_b = next(b for b in workout.blocks if b.block_type.value == "b")
    assert block_b.is_heavy is False
    assert block_b.target_after == block_b.target_before  # блок Б бэкдейта всегда вне пересчёта (issue #88)
