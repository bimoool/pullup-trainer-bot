from datetime import UTC, datetime
from decimal import Decimal

from app.domain.constants import STRENGTH_BLOCK, VOLUME_BLOCK, EquipmentType
from app.domain.progression import recalculate_cascade, recalculate_target, recalculate_volume_block
from app.domain.progression_strategy import (
    PercentageProgressionContext,
    PercentageProgressionStrategy,
    ProgressionContext,
    StepProgressionStrategy,
)
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord


def _block_assignment(
    working_reps, max_reps, target_before, equipment_type=EquipmentType.BAND, is_deload=False, is_heavy=False,
    equipment_value=None,
):
    return BlockAssignment(
        log=BlockLog(working_reps=working_reps, max_reps=max_reps),
        target_before=target_before,
        target_after=0,
        equipment_changed=False,
        equipment_type=equipment_type,
        equipment_value=equipment_value,
        is_deload=is_deload,
        is_heavy=is_heavy,
    )


# --- StepProgressionStrategy ------------------------------------------------

def test_step_strategy_apply_delegates_to_recalculate_cascade_unchanged():
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((17, 17, 17), 19, target_before=0),
        block_b=_block_assignment((5, 5, 5, 5), 6, target_before=0),
    )
    context = ProgressionContext(
        starting_target_a=17, starting_target_b=5, starting_volume_a=68, starting_volume_b=21,
        subsequent_workouts=[record],
    )

    result = StepProgressionStrategy().apply(context)

    assert result == recalculate_cascade(17, 5, 68, 21, [record])


def test_step_strategy_preview_is_the_same_call_as_apply_not_a_separate_copy():
    """Критерий готовности issue #158: preview() должен давать те же
    значения, что apply(). StepProgressionStrategy.preview буквально
    вызывает apply() — не отдельно продублированный расчёт, который
    "должен" совпасть, поэтому расхождение между ними физически
    невозможно, а не просто не встретилось в тестах."""
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 5, tzinfo=UTC),
        block_a=_block_assignment((10, 10, 8), 9, target_before=0),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )
    context = ProgressionContext(
        starting_target_a=10, starting_target_b=3, starting_volume_a=40, starting_volume_b=12,
        subsequent_workouts=[record], starting_weak_streak_a=2,
    )
    strategy = StepProgressionStrategy()

    assert strategy.preview(context) == strategy.apply(context)


def test_prepending_edited_record_to_cascade_matches_old_manual_single_block_path():
    """Волна 0 (issue #158, план п.2, подтверждено Кириллом) — объединение
    "пересчёт себя" + "пересчёт следующих" в один вызов recalculate_cascade
    (см. WorkoutRepository._build_edit_context) должно давать побитово тот
    же результат для отредактированной записи, что и старый ручной путь:
    прямой вызов recalculate_volume_block/recalculate_target на ней одной.
    Держит "старый путь" как reference-расчёт прямо в тесте (см. "Стиль
    тестирования" в CLAUDE.md), а не полагается на чтение кода."""
    target_before_a, target_before_b = 17, 5
    prev_volume_a, prev_volume_b = 68, 21
    weak_streak_a, weak_streak_b = 1, 0
    work_sets_a = VOLUME_BLOCK.work_sets
    stall_streak_a = 2
    equipment_type_a = EquipmentType.BAND

    new_block_a_reps = BlockLog(working_reps=(18, 18, 18), max_reps=19)
    new_block_b_reps = BlockLog(working_reps=(5, 5, 5, 5), max_reps=6)

    # --- старый ручной путь (reference, как было в edit_workout ДО волны 0) ---
    reference_a = recalculate_volume_block(
        target_before_a, work_sets_a, new_block_a_reps.working_reps, new_block_a_reps.max_reps,
        new_block_a_reps.volume, prev_volume_a, equipment_type_a,
        consecutive_weak_before=weak_streak_a, consecutive_stall_before=stall_streak_a,
    )
    reference_b = recalculate_target(
        STRENGTH_BLOCK, target_before_b, new_block_b_reps.working_reps, new_block_b_reps.max_reps,
        new_block_b_reps.volume, prev_volume_b, consecutive_weak_before=weak_streak_b,
    )

    # --- новый объединённый путь: сама запись — просто первый элемент цепочки ---
    edited_record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment(
            new_block_a_reps.working_reps, new_block_a_reps.max_reps, target_before=0,
            equipment_type=equipment_type_a,
        ),
        block_b=_block_assignment(new_block_b_reps.working_reps, new_block_b_reps.max_reps, target_before=0),
    )
    updated = recalculate_cascade(
        starting_target_a=target_before_a, starting_target_b=target_before_b,
        starting_volume_a=prev_volume_a, starting_volume_b=prev_volume_b,
        subsequent_workouts=[edited_record],
        starting_weak_streak_a=weak_streak_a, starting_weak_streak_b=weak_streak_b,
        starting_work_sets_a=work_sets_a, starting_stall_streak_a=stall_streak_a,
    )
    unified = updated[0]

    assert unified.block_a.target_after == reference_a.new_target
    assert unified.block_a.work_sets_after == reference_a.new_work_sets
    assert unified.block_a.equipment_changed == reference_a.equipment_changed
    assert unified.block_b.target_after == reference_b.new_target
    assert unified.block_b.equipment_changed == reference_b.equipment_changed


def test_recalculate_cascade_with_prepended_record_is_sensitive_to_starting_stall_streak():
    """Доказательство, что сравнение выше реально чувствительно к параметрам
    (не тавтология "то же самое написано дважды"): если бы
    WorkoutRepository._build_edit_context забыл пробросить
    starting_stall_streak_a (легко допустимая ошибка при переносе кода),
    результат бы отличался — эта чувствительность и есть то, что ловит
    такой баг в тесте выше, если бы он туда закрался."""
    target_a, work_sets_a = 20, 3
    working_reps, max_reps = (15, 15, 15), 16  # delta = 16-20 = -4 <= 0, застой/провал, не рост
    prev_volume = 999  # весь объём заведомо меньше prev_volume -> "слабая", но weak_streak=0 не откатывает цель

    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment(working_reps, max_reps, target_before=0, equipment_type=EquipmentType.BODYWEIGHT),
        block_b=_block_assignment((3, 3, 3, 3), 3, target_before=0),
    )

    with_stall_streak = recalculate_cascade(
        starting_target_a=target_a, starting_target_b=5, starting_volume_a=prev_volume, starting_volume_b=21,
        subsequent_workouts=[record], starting_work_sets_a=work_sets_a, starting_stall_streak_a=3,
    )
    without_stall_streak = recalculate_cascade(
        starting_target_a=target_a, starting_target_b=5, starting_volume_a=prev_volume, starting_volume_b=21,
        subsequent_workouts=[record], starting_work_sets_a=work_sets_a, starting_stall_streak_a=0,
    )

    assert with_stall_streak[0].block_a.work_sets_after == work_sets_a + 1  # 3+1>=VOLUME_STALL_THRESHOLD(4)
    assert without_stall_streak[0].block_a.work_sets_after == work_sets_a  # 0+1<4, застойный счётчик не набрался


# --- PercentageProgressionStrategy ------------------------------------------

def _percentage_record() -> WorkoutRecord:
    return WorkoutRecord(
        performed_at=datetime(2026, 1, 3, tzinfo=UTC),
        block_a=_block_assignment((10, 10, 10), 11, target_before=10),
        block_b=_block_assignment((5, 5, 5, 5), 5, target_before=5),
    )


def test_percentage_strategy_sets_block_b_target_to_percentage_of_test_result():
    strategy = PercentageProgressionStrategy(Decimal("0.9"))
    context = PercentageProgressionContext(test_result=20, subsequent_workouts=[_percentage_record()])

    updated = strategy.apply(context)

    assert len(updated) == 1
    assert updated[0].block_b.target_after == 18  # round(0.9 * 20)
    assert updated[0].block_b.target_before == 18
    assert updated[0].block_b.equipment_changed is False


def test_percentage_strategy_leaves_block_a_untouched():
    """Эта демо-стратегия описывает прогрессию только одного измерения
    (аналог "90% от 2ПМ" у Crimpd) — блок A не в её ведении вообще."""
    record = _percentage_record()
    strategy = PercentageProgressionStrategy(Decimal("0.9"))
    context = PercentageProgressionContext(test_result=20, subsequent_workouts=[record])

    updated = strategy.apply(context)

    assert updated[0].block_a == record.block_a


def test_percentage_strategy_uses_banker_rounding_like_the_rest_of_the_domain():
    strategy = PercentageProgressionStrategy(Decimal("0.25"))

    # 0.25 * 10 = 2.5 -> ближайшее чётное -> 2
    context_even = PercentageProgressionContext(test_result=10, subsequent_workouts=[_percentage_record()])
    assert strategy.apply(context_even)[0].block_b.target_after == 2

    # 0.25 * 14 = 3.5 -> ближайшее чётное -> 4
    context_up = PercentageProgressionContext(test_result=14, subsequent_workouts=[_percentage_record()])
    assert strategy.apply(context_up)[0].block_b.target_after == 4


def test_percentage_strategy_applies_the_same_target_regardless_of_position():
    """Нет каскадной арифметики/бегущего состояния — все записи получают
    один и тот же target, вычисленный из test_result, независимо от их
    собственного target_before."""
    high_target_record = WorkoutRecord(
        performed_at=datetime(2026, 1, 4, tzinfo=UTC),
        block_a=_block_assignment((10, 10, 10), 11, target_before=10),
        block_b=_block_assignment((50, 50, 50, 50), 50, target_before=50),
    )
    strategy = PercentageProgressionStrategy(Decimal("0.9"))
    context = PercentageProgressionContext(
        test_result=20, subsequent_workouts=[_percentage_record(), high_target_record],
    )

    updated = strategy.apply(context)

    assert updated[0].block_b.target_after == 18
    assert updated[1].block_b.target_after == 18


def test_percentage_strategy_preview_is_the_same_call_as_apply():
    strategy = PercentageProgressionStrategy(Decimal("0.5"))
    context = PercentageProgressionContext(test_result=10, subsequent_workouts=[_percentage_record()])

    assert strategy.preview(context) == strategy.apply(context)
