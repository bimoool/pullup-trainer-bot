import math
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from statistics import mean

from app.domain.constants import (
    HEAVY_BLOCK_FIXED_REPS,
    HEAVY_BLOCK_MEDIAN_REPS,
    HEAVY_GROWTH_MAX_REPS_THRESHOLD,
    HEAVY_WEIGHT_ROUND_TO_KG,
    ROLLBACK_REPS,
    ROLLBACK_WEIGHT_PCT,
    STEP_PCT,
    STRENGTH_BLOCK,
    STRENGTH_START_BODYWEIGHT_MIN_REPS,
    STRENGTH_START_WEIGHT_MIN_REPS,
    TRANSITION_RETRY_WORKOUTS,
    VOLUME_BIG_OVERSHOOT_THRESHOLD,
    VOLUME_BLOCK,
    VOLUME_MODERATE_ROLLBACK_TARGET,
    VOLUME_STALL_THRESHOLD,
    VOLUME_TARGET_CEILING,
    VOLUME_WEIGHT_MIN_STEP_KG,
    VOLUME_WORK_SETS_CEILING,
    WEAK_STREAK_ROLLBACK_THRESHOLD,
    WEIGHT_ROUND_TO_KG,
    BlockConfig,
    EquipmentType,
    VolumeGrowthReason,
    epley_multiplier,
    to_signed_load,
)
from app.domain.session import BlockAssignment, WorkoutRecord


@dataclass(frozen=True)
class ProgressionResult:
    """Результат пересчёта цели по одному блоку.

    equipment_changed=True означает, что new_target уже сброшен на
    block.base_target — снаряд меняется на следующий по шкале. Какой именно
    (толщина резины/конкретный вес) — вне домена, пользователь вводит сам.
    """

    new_target: int
    equipment_changed: bool


def recalculate_target(
    block: BlockConfig,
    target: int,
    working_reps: tuple[int, ...],
    max_reps: int,
    volume: int,
    prev_volume: int,
    consecutive_weak_before: int = 0,
) -> ProgressionResult:
    """Единая формула пересчёта цели для объёмного и силового блока (пятая
    по счёту правка этой функции). Раньше принимала equipment_type — убран:
    это был единственный потребитель (старый bodyweight_ceiling=25 для
    объёмного блока), потолок заменён новой системой в
    recalculate_volume_block, которая оборачивает эту функцию, а не меняет
    её контракт.

    Вход в ветку успеха/провала решает delta = max_reps - target, как и
    раньше. Внутри ветки успеха шаг роста теперь ПРОЦЕНТНЫЙ — 5% от
    текущей цели (STEP_PCT), не от степени перевыполнения максимума:

        avg_working = mean(working_reps)
        step = max(1, ceil(target * STEP_PCT))
        new_target = round(avg_working) + step

    Осознанное следствие (не баг): шаг больше НЕ зависит от того, насколько
    сильно max_reps превысил цель — только от текущей нагрузки. Раньше был
    min(MAX_STEP, ceil(growth * coef)), где growth = max_reps - avg_working;
    это заменено целиком, а не дополнено.

    round() — обычное (Python round-half-to-even), для согласованности с
    остальной кодовой базой; не критично, по просьбе зафиксировано явно.
    max(1, ...) вокруг step (не max(0, ...), как было раньше) — шаг теперь
    ВСЕГДА положителен вне зависимости от вырожденного ввода (working_reps
    не обязаны быть <= max_reps, парсер этого не проверяет), поэтому
    new_target гарантированно строго больше round(avg_working), даже при
    испорченных данных — защита от абсурдного отката получается сама
    собой, отдельный max(0, ...) для неё больше не нужен.

    Ветка провала (delta <= 0) — с отсрочкой отката: "слабая" тренировка —
    объём меньше предыдущего; цель откатывается на -1 только после
    WEAK_STREAK_ROLLBACK_THRESHOLD (3) подряд слабых, не после первой.
    consecutive_weak_before — сколько таких подряд БЫЛО до этой тренировки,
    считает вызывающий код из истории (см. count_consecutive_weak_trainings)
    — домен сам историю не хранит.

    Снаряд меняется, когда КАЖДЫЙ элемент working_reps (рабочие подходы,
    без учёта подхода на максимум) достиг block.equipment_change_threshold —
    сравнение идёт с фактическими повторениями, не с расчётной new_target
    ("20 20 20 21" — порог взят; "19 19 19 22" — нет, хотя максимум выше).
    """
    new_target = _compute_raw_target(target, working_reps, max_reps, volume, prev_volume, consecutive_weak_before)

    threshold_hit = bool(working_reps) and all(r >= block.equipment_change_threshold for r in working_reps)
    if threshold_hit:
        return ProgressionResult(new_target=block.base_target, equipment_changed=True)

    return ProgressionResult(new_target=new_target, equipment_changed=False)


def _compute_raw_target(
    target: int, working_reps: tuple[int, ...], max_reps: int, volume: int, prev_volume: int,
    consecutive_weak_before: int,
) -> int:
    """Арифметика делта/шаг/откат БЕЗ проверки порога смены снаряда —
    вынесена отдельно от recalculate_target, потому что
    recalculate_volume_block на этапе BODYWEIGHT (иерархия роста, часть 2)
    должна расти по этой формуле НАПРЯМУЮ, не рискуя получить
    threshold-сброс на base_target вместо честного расчётного значения
    (общий порог смены снаряда на этом этапе подавлен целиком — см.
    recalculate_volume_block)."""
    delta = max_reps - target
    if delta > 0:
        avg_working = mean(working_reps) if working_reps else float(target)
        step = max(1, math.ceil(target * STEP_PCT))
        return round(avg_working) + step
    if delta == 0:
        return target
    is_weak = volume < prev_volume
    if is_weak and consecutive_weak_before + 1 >= WEAK_STREAK_ROLLBACK_THRESHOLD:
        return target - 1
    return target


def count_consecutive_weak_trainings(volumes: list[int]) -> int:
    """Сколько подряд идущих "слабых" тренировок (Часть 10, пакет #2,
    п.13) стоят в конце volumes — хронологического списка объёмов ОДНОГО
    блока, НЕ включая тренировку, для которой сейчас считается
    consecutive_weak_before. "Слабая" — объём меньше, чем у той, что
    непосредственно перед ней (volumes[i] < volumes[i-1]); первый элемент
    списка сам по себе не может быть "слабым" — сравнивать не с чем.

    Вычисляется каждый раз заново из истории (list_for_user/каскад) — не
    хранимый счётчик, тот же принцип, что уже применён к повторным
    попыткам смены снаряда (is_retry_allowed) и к needs_new_equipment."""
    count = 0
    for i in range(len(volumes) - 1, 0, -1):
        if volumes[i] < volumes[i - 1]:
            count += 1
        else:
            break
    return count


def count_consecutive_stalled_workouts(grew_flags: list[bool]) -> int:
    """Сколько подряд идущих тренировок В КОНЦЕ grew_flags НЕ вырастили
    блок на объём — "застой" (иерархия роста, п.2): триггер для +1
    рабочего подхода после VOLUME_STALL_THRESHOLD (4) подряд.

    Аналог count_consecutive_weak_trainings, но сигнал другой — не объём
    тренировки, а сам факт роста БЛОКА в любом из двух измерений: рост
    цели (target_after > target_before) ИЛИ рост числа рабочих подходов
    (work_sets_after > work_sets_before). Добавление подхода (по правилу
    застоя или по потолку повторений, см. recalculate_volume_block) — это
    тоже рост, просто другого рода, и должно сбрасывать застойный счётчик
    так же, как рост цели — иначе один и тот же застой считался бы дважды.

    grew_flags — booleans в хронологическом порядке (старые первыми),
    вычисляет вызывающий код из истории блока А."""
    count = 0
    for grew in reversed(grew_flags):
        if grew:
            break
        count += 1
    return count


@dataclass(frozen=True)
class VolumeBlockResult:
    """Результат пересчёта СПЕЦИФИЧНО для блока на объём — расширяет
    ProgressionResult новым измерением состояния (иерархия роста, части
    2-3 ревизии формулы): числом рабочих подходов. Силовой блок как был на
    recalculate_target, так и остаётся — этой многомерности у него нет.

    Вес НЕ считается здесь — это не факт результата ПРОШЕДШЕЙ тренировки
    (как target/work_sets), а предложение на СЛЕДУЮЩУЮ, вычисляемое из
    последнего фактического equipment_value репозиторием (см.
    grow_volume_weight_kg и WorkoutRepository._resolve_next_state), тем же
    принципом, что уже применён к suggest_weight_range для силового блока —
    домен не решает за пользователя, что тот "использовал", только
    подсказывает следующий шаг.

    work_sets_growth_reason — None, если new_work_sets не выросло по
    сравнению с переданным work_sets (в т.ч. когда оно уже заморожено на
    потолке — см. recalculate_volume_block, п.1 и "уже на потолке 8
    подходов"), иначе STALL/CEILING в зависимости от того, какая из двух
    веток роста подходов сработала."""

    new_target: int
    new_work_sets: int
    equipment_changed: bool
    work_sets_growth_reason: VolumeGrowthReason | None = None


def grow_volume_weight_kg(current_kg: Decimal) -> Decimal:
    """Предложенный следующий вес блока на объём после перехода на
    отягощение (часть 3) — тот же процентный шаг (STEP_PCT=5%), что и у
    повторений, минимум +VOLUME_WEIGHT_MIN_STEP_KG (0.5кг) до округления,
    затем округление вверх до ближайшего шага блинов (WEIGHT_ROUND_TO_KG)
    — та же функция округления, что уже использует suggest_weight_range
    для силового блока. Растёт БЕЗУСЛОВНО каждую тренировку на отягощении
    (цель/подходы уже заморожены, дальнейший рост возможен только так — не
    привязан к тому, справился ли человек с 33×8 или нет, в промпте это не
    оговорено как условие)."""
    step = max(VOLUME_WEIGHT_MIN_STEP_KG, float(current_kg) * STEP_PCT)
    grown = _ceil_to_step(float(current_kg) + step, WEIGHT_ROUND_TO_KG)
    return Decimal(str(grown))


def recalculate_volume_block(
    target: int,
    work_sets: int,
    working_reps: tuple[int, ...],
    max_reps: int,
    volume: int,
    prev_volume: int,
    equipment_type: EquipmentType,
    consecutive_weak_before: int = 0,
    consecutive_stall_before: int = 0,
) -> VolumeBlockResult:
    """Иерархия роста блока на объём (ревизия формулы, части 2-3) — ПОВЕРХ
    recalculate_target, не вместо неё: базовая арифметика успех/провал и
    процентный шаг общие для обоих блоков (часть 1), здесь только то, что
    специфично для объёмного — доп. подходы при застое/потолке и переход
    на отягощение.

    Порядок проверки за одну тренировку (согласовано в плане, "по порядку,
    не одновременно"):

    1. Уже на отягощении (equipment_type=WEIGHT и work_sets уже на
       потолке) — цель/подходы заморожены на потолке, дальше растёт
       только вес (см. grow_volume_weight_kg — не здесь, это забота
       _resolve_next_state при построении подсказки на СЛЕДУЮЩУЮ
       тренировку). Всё остальное ниже не применяется.
    2. Иначе считаем базовый результат через recalculate_target. На BAND —
       обычный порог смены снаряда (BAND→BODYWEIGHT) работает как раньше,
       без изменений. На BODYWEIGHT — общий порог ПОДАВЛЯЕТСЯ: дальнейший
       рост с этой точки полностью ведёт эта функция, не общий механизм
       смены снаряда (иначе он увёл бы на WEIGHT рано, через порог 20, в
       обход системы потолка 33/8).
    3. Если считается рост (delta>0) и расчётная цель дошла до
       VOLUME_TARGET_CEILING (33 — тот же порог, что и старт блока сразу
       с отягощением по замеру, см. suggest_starting_equipment):
       - подходы уже на потолке (8) — переход на отягощение СРАЗУ в этой
         же тренировке (расти по подходам уже некуда) — new_target/
         new_work_sets замораживаются на потолке, equipment_type для
         СЛЕДУЮЩЕЙ тренировки решит _resolve_next_state (видит
         work_sets_after==потолок и target_after==потолок → WEIGHT).
       - иначе, расчётная цель < VOLUME_BIG_OVERSHOOT_THRESHOLD (50) —
         откат до VOLUME_MODERATE_ROLLBACK_TARGET (20), +1 подход.
       - иначе (>= 50) — откат до потолка (33), подходов добавляется
         ceil(расчётная_цель / VOLUME_TARGET_CEILING) — превращает "один
         гигантский подход на X" в разумное число подходов по потолку
         каждый. Если это ДОВЕЛО work_sets ровно до 8 — переход на
         отягощение начнётся со СЛЕДУЮЩЕЙ тренировки, не в этой (тот же
         механизм в _resolve_next_state, что и в пункте выше).
    4. Иначе (застой, delta<=0 и НЕ выросло) — если застойный счётчик
       (включая эту тренировку) достиг VOLUME_STALL_THRESHOLD (4) и
       подходы ещё не на потолке — +1 подход, цель как посчитана
       (flat/откат по обычной формуле, без изменений).
    5. Как только work_sets == VOLUME_WORK_SETS_CEILING (8) — ни застой,
       ни потолок повторений больше не добавляют подходов (последующий
       рост только через п.1/переход на вес)."""
    if equipment_type == EquipmentType.WEIGHT and work_sets >= VOLUME_WORK_SETS_CEILING:
        return VolumeBlockResult(
            new_target=VOLUME_TARGET_CEILING, new_work_sets=VOLUME_WORK_SETS_CEILING, equipment_changed=False,
        )

    if equipment_type == EquipmentType.BAND:
        base = recalculate_target(
            VOLUME_BLOCK, target, working_reps, max_reps, volume, prev_volume,
            consecutive_weak_before=consecutive_weak_before,
        )
        if base.equipment_changed:
            return VolumeBlockResult(new_target=base.new_target, new_work_sets=work_sets, equipment_changed=True)
        computed_target = base.new_target
    else:
        # BODYWEIGHT (или WEIGHT ниже потолка подходов, если такое вообще
        # возможно) — общий порог смены снаряда полностью подавлен, растим
        # напрямую по формуле. НЕ через recalculate_target: если бы working
        # reps СЛУЧАЙНО заодно перевалили за equipment_change_threshold
        # (20), тот вернул бы new_target=base_target(10) вместо честного
        # расчётного значения — здесь это было бы неверной "просадкой" и
        # исказило бы всю иерархию роста ниже.
        computed_target = _compute_raw_target(
            target, working_reps, max_reps, volume, prev_volume, consecutive_weak_before,
        )

    grew = computed_target > target

    if grew and computed_target >= VOLUME_TARGET_CEILING:
        if work_sets >= VOLUME_WORK_SETS_CEILING:
            return VolumeBlockResult(
                new_target=VOLUME_TARGET_CEILING, new_work_sets=VOLUME_WORK_SETS_CEILING, equipment_changed=False,
            )
        if computed_target < VOLUME_BIG_OVERSHOOT_THRESHOLD:
            new_target = VOLUME_MODERATE_ROLLBACK_TARGET
            new_work_sets = min(VOLUME_WORK_SETS_CEILING, work_sets + 1)
        else:
            new_target = VOLUME_TARGET_CEILING
            sets_to_add = math.ceil(computed_target / VOLUME_TARGET_CEILING)
            new_work_sets = min(VOLUME_WORK_SETS_CEILING, work_sets + sets_to_add)
        reason = VolumeGrowthReason.CEILING if new_work_sets > work_sets else None
        return VolumeBlockResult(
            new_target=new_target, new_work_sets=new_work_sets, equipment_changed=False,
            work_sets_growth_reason=reason,
        )

    new_work_sets = work_sets
    if (
        not grew
        and work_sets < VOLUME_WORK_SETS_CEILING
        and consecutive_stall_before + 1 >= VOLUME_STALL_THRESHOLD
    ):
        new_work_sets = work_sets + 1

    reason = VolumeGrowthReason.STALL if new_work_sets > work_sets else None
    return VolumeBlockResult(
        new_target=computed_target, new_work_sets=new_work_sets, equipment_changed=False,
        work_sets_growth_reason=reason,
    )


def suggest_starting_equipment(baseline_reps: int) -> tuple[EquipmentType, EquipmentType]:
    """(объёмный, силовой) — стартовый тип снаряда по итогам замера (только
    число подтягиваний на собственном весе). Точное сопротивление резины
    или вес отягощения бот не подбирает — пользователь вводит фактическое
    на первой тренировке, здесь только тип.

    У каждого блока СВОИ пороги (Часть 10 — раньше по ошибке оба блока
    считались по порогу объёмного, силовой блок никогда не получал
    "отягощение" даже при большом замере):
    - объёмный: отягощение сразу при замере >= VOLUME_TARGET_CEILING (33,
      ревизия v5 — тот же порог, что и внутренний потолок иерархии роста,
      сознательно одна константа: не гонять человека через долгий подъём
      с собственного веса, если он уже явно готов к весу с самого начала);
      иначе свой вес при замере > VOLUME_BLOCK.base_target (10); иначе резина;
    - силовой: отягощение при замере >= STRENGTH_START_WEIGHT_MIN_REPS (8),
      свой вес при STRENGTH_START_BODYWEIGHT_MIN_REPS (3) <= замер < 8,
      иначе (замер < 3) резина.
    """
    if baseline_reps >= VOLUME_TARGET_CEILING:
        volume_equipment = EquipmentType.WEIGHT
    elif baseline_reps > VOLUME_BLOCK.base_target:
        volume_equipment = EquipmentType.BODYWEIGHT
    else:
        volume_equipment = EquipmentType.BAND

    if baseline_reps >= STRENGTH_START_WEIGHT_MIN_REPS:
        strength_equipment = EquipmentType.WEIGHT
    elif baseline_reps >= STRENGTH_START_BODYWEIGHT_MIN_REPS:
        strength_equipment = EquipmentType.BODYWEIGHT
    else:
        strength_equipment = EquipmentType.BAND

    return volume_equipment, strength_equipment


def initial_volume_target(baseline_reps: int) -> int:
    """Начальная цель объёмного блока при старте (первая тренировка/
    ретест) — Часть 10, пакет #2, п.14, "замер минус 25%".

    Старт на собственном весе (замер > VOLUME_BLOCK.base_target, см.
    suggest_starting_equipment) — начальная цель ceil(замер * 0.75), не
    флэт base_target: сразу отталкивается от реального уровня, а не
    занижает его до дефолтных 10. Округление вверх.

    Старт с резины (замер <= base_target) — без изменений: подбираем
    резину под ~base_target повторений, стартуем flat base_target-
    base_target-base_target-макс, как и раньше."""
    if baseline_reps > VOLUME_BLOCK.base_target:
        return math.ceil(baseline_reps * 0.75)
    return VOLUME_BLOCK.base_target


class TransitionOutcome(StrEnum):
    """Результат проверки первой тренировки на новом снаряде."""

    NOT_APPLICABLE = "not_applicable"  # не первая тренировка на этом снаряде — проверка не при делах
    VIABLE = "viable"
    FAILED = "failed"  # максимум ниже min_viable_reps — снаряд подобран неверно


def check_transition_outcome(
    block: BlockConfig, max_reps: int, *, is_first_workout_on_new_gear: bool,
) -> TransitionOutcome:
    """Проверка идёт по факту тренировки (не пробным подходом заранее) —
    is_first_workout_on_new_gear вычисляет вызывающий код по истории (он и
    так знает equipment_changed предыдущей тренировки), домен остаётся
    чистым от истории."""
    if not is_first_workout_on_new_gear:
        return TransitionOutcome.NOT_APPLICABLE
    return TransitionOutcome.VIABLE if max_reps >= block.min_viable_reps else TransitionOutcome.FAILED


def is_retry_allowed(workouts_since_revert: int) -> bool:
    """После неудачного перехода — TRANSITION_RETRY_WORKOUTS (4) тренировок
    на прежнем снаряде, прежде чем снова предлагать переход."""
    return workouts_since_revert >= TRANSITION_RETRY_WORKOUTS


def _ceil_to_step(value: float, step: float) -> float:
    # round() перед ceil/floor гасит шум плавающей точки (1e-9 << 1.25),
    # чтобы значение, которое математически ровно на шаге, не съезжало
    # на следующий шаг из-за представления float.
    ratio = round(value / step, 9)
    return round(math.ceil(ratio) * step, 2)


def _floor_to_step(value: float, step: float) -> float:
    ratio = round(value / step, 9)
    return round(math.floor(ratio) * step, 2)


def suggest_weight_range(current_weight_kg: Decimal) -> tuple[Decimal, Decimal] | None:
    """Диапазон рекомендованной прибавки при переходе силового блока на
    больший вес (+10–15%) — бот больше не считает точный новый вес сам
    (было раньше — next_weight_kg), только подсказывает диапазон,
    пользователь вводит фактический вес, с которым стал заниматься.

    None, если current_weight_kg <= 0 — это переход с собственного веса
    НА отягощение впервые, процент от нуля ничего не значит; в этом случае
    пользователю нужно предложить взять небольшой стартовый вес, а не
    процентный диапазон (это уже забота вызывающего кода/текстов).
    """
    if current_weight_kg <= 0:
        return None
    low = _ceil_to_step(float(current_weight_kg) * 1.10, WEIGHT_ROUND_TO_KG)
    high = _ceil_to_step(float(current_weight_kg) * 1.15, WEIGHT_ROUND_TO_KG)
    return Decimal(str(low)), Decimal(str(high))


def suggest_heavy_weight_kg(normal_weight_kg: Decimal) -> Decimal:
    """Вес для чётной ("тяжёлой") тренировки блока Б (issue #97) — через
    формулу Эпли от текущего обычного веса силового блока: медиана
    HEAVY_BLOCK_MEDIAN_REPS (5) повторений обычного блока переводится в
    эквивалент 1ПМ, оттуда обратно — вес на HEAVY_BLOCK_FIXED_REPS (3)
    повторения. Округление вверх до HEAVY_WEIGHT_ROUND_TO_KG (0.5 — НЕ
    WEIGHT_ROUND_TO_KG, шаг для этого случая подтверждён автором продукта
    отдельно, см. константу).

    Вызывается только один раз — перед самой первой тяжёлой тренировкой
    (предыдущей тяжёлой ещё не было в истории); дальше подсказку несёт сама
    история тяжёлых тренировок, см. resolve_heavy_weight_growth и
    WorkoutRepository._resolve_next_state (ищет последний тяжёлый Block)."""
    one_rm_equivalent = normal_weight_kg * epley_multiplier(HEAVY_BLOCK_MEDIAN_REPS)
    heavy = float(one_rm_equivalent / epley_multiplier(HEAVY_BLOCK_FIXED_REPS))
    return Decimal(str(_ceil_to_step(heavy, HEAVY_WEIGHT_ROUND_TO_KG)))


def resolve_heavy_weight_growth(max_reps: int, current_heavy_weight_kg: Decimal) -> Decimal:
    """Подсказка веса на СЛЕДУЮЩУЮ тяжёлую тренировку по факту последней
    (issue #97, решение автора продукта после ревизии плана): пятый подход
    (тот же смысл, что "подход на максимум" обычного силового блока) >=
    HEAVY_GROWTH_MAX_REPS_THRESHOLD (5) — рост на HEAVY_WEIGHT_ROUND_TO_KG,
    иначе вес остаётся прежним. Без отката при провале — согласовано явно,
    "не откатываем вес при провале, просто не растим": простой порог по
    ОДНОЙ тренировке, не стрик из нескольких подряд, как у обычного
    силового блока (WEAK_STREAK_ROLLBACK_THRESHOLD)."""
    if max_reps >= HEAVY_GROWTH_MAX_REPS_THRESHOLD:
        grown = _ceil_to_step(float(current_heavy_weight_kg) + HEAVY_WEIGHT_ROUND_TO_KG, HEAVY_WEIGHT_ROUND_TO_KG)
        return Decimal(str(grown))
    return current_heavy_weight_kg


def rollback_target(target: int) -> int:
    """Откат цели объёмного блока при пропуске 21–35 дней: target - ROLLBACK_REPS."""
    return target - ROLLBACK_REPS


def rollback_signed_load(equipment_type: EquipmentType, equipment_value: Decimal) -> Decimal:
    """Предлагаемая нагрузка силового блока после отката (перерыв 21–35
    дней) — тот же снаряд, но примерно на ROLLBACK_WEIGHT_PCT (10%) легче
    ПО ЗНАКОВОЙ ШКАЛЕ (см. to_signed_load): знаковая величина должна
    УМЕНЬШИТЬСЯ в обоих случаях — для отягощения это меньший вес
    (+20 → +18), для резины — БОЛЬШЕЕ сопротивление в кг, то есть больше
    помощи (−30 → −33, кг резины 30 → 33).

    Именно поэтому здесь нельзя просто умножить |equipment_value| на 0.9:
    для резины это утащило бы знаковую величину К НУЛЮ (−30·0.9 = −27),
    то есть сделало бы снаряд ЖёстЧЕ — прямо противоположно смыслу отката.
    Вместо этого вычитаем долю МОДУЛЯ из знакового значения — это всегда
    двигает его в сторону "легче" независимо от знака.

    Округление — в сторону ещё легче (floor знакового значения), чтобы
    фактическое снижение нагрузки было не меньше заявленных 10%, как и в
    прежней (дошкальной) версии этой функции. Возвращает магнитуду
    (положительное число) — то, что показать пользователю в кг."""
    signed = to_signed_load(equipment_type, equipment_value)
    rolled_back_signed = float(signed) - abs(float(signed)) * ROLLBACK_WEIGHT_PCT
    floored = _floor_to_step(rolled_back_signed, WEIGHT_ROUND_TO_KG)
    return Decimal(str(abs(floored)))


def recalculate_cascade(
    starting_target_a: int,
    starting_target_b: int,
    starting_volume_a: int,
    starting_volume_b: int,
    subsequent_workouts: list[WorkoutRecord],
    starting_weak_streak_a: int = 0,
    starting_weak_streak_b: int = 0,
    starting_work_sets_a: int = VOLUME_BLOCK.work_sets,
    starting_stall_streak_a: int = 0,
) -> list[WorkoutRecord]:
    """Каскадный пересчёт цепочки тренировок после редактирования более
    ранней тренировки. Остаётся только для этого сценария — внесённые
    задним числом тренировки в каскад не входят вовсе (фильтрует
    вызывающий код, см. WorkoutRepository).

    starting_target_a/b — цели, которые действуют СРАЗУ ПОСЛЕ
    отредактированной тренировки. starting_volume_a/b — её объёмы, нужны
    как prev_volume для первой тренировки из subsequent_workouts.
    starting_weak_streak_a/b — сколько подряд слабых тренировок было ДО
    начала этой цепочки (считает вызывающий код из истории вплоть до
    отредактированной тренировки включительно, см.
    WorkoutRepository.edit_workout) — дальше счётчик бегущий, обновляется
    по ходу цикла, отдельно нигде не хранится. starting_work_sets_a/
    starting_stall_streak_a — то же самое для новой иерархии роста блока
    на объём (застой/потолок подходов, см. recalculate_volume_block);
    только для блока A — у силового блока подходы фиксированы.

    equipment_type и transition_failed каждой записи не пересчитываются —
    это факт того, что было в реальности, каскад его не переигрывает.
    Блок A с is_deload=True полностью выключен из пересчёта (часть 4
    ревизии формулы: разгрузочная тренировка не двигает и не откатывает
    прогрессию) — target/work_sets/весовые/стрик-счётчики проходят через
    такую запись без изменений, как будто её не было. Блок Б с is_heavy=True
    (чётная "тяжёлая" тренировка, issue #97) выключен из пересчёта тем же
    приёмом — target_before_b/target_after_b и weak_streak_b/prev_volume_b
    проходят через неё без изменений; фактический вес (equipment_value) и
    результат (log) при этом сохраняются как есть, каскад их не трогает,
    только не даёт им сдвинуть прогрессию обычных (нечётных) тренировок."""
    updated: list[WorkoutRecord] = []
    target_a, target_b = starting_target_a, starting_target_b
    prev_volume_a, prev_volume_b = starting_volume_a, starting_volume_b
    weak_streak_a, weak_streak_b = starting_weak_streak_a, starting_weak_streak_b
    work_sets_a = starting_work_sets_a
    stall_streak_a = starting_stall_streak_a

    for record in subsequent_workouts:
        if record.block_a.is_deload:
            block_a_assignment = BlockAssignment(
                log=record.block_a.log,
                target_before=target_a,
                target_after=target_a,
                equipment_changed=False,
                equipment_type=record.block_a.equipment_type,
                equipment_value=record.block_a.equipment_value,
                equipment_item_id=record.block_a.equipment_item_id,
                transition_failed=record.block_a.transition_failed,
                work_sets_before=work_sets_a,
                work_sets_after=work_sets_a,
                is_deload=True,
            )
        else:
            result_a = recalculate_volume_block(
                target_a, work_sets_a, record.block_a.log.working_reps, record.block_a.log.max_reps,
                record.block_a.log.volume, prev_volume_a, record.block_a.equipment_type,
                consecutive_weak_before=weak_streak_a, consecutive_stall_before=stall_streak_a,
            )
            block_a_assignment = BlockAssignment(
                log=record.block_a.log,
                target_before=target_a,
                target_after=result_a.new_target,
                equipment_changed=result_a.equipment_changed,
                equipment_type=record.block_a.equipment_type,
                equipment_value=record.block_a.equipment_value,
                equipment_item_id=record.block_a.equipment_item_id,
                transition_failed=record.block_a.transition_failed,
                work_sets_before=work_sets_a,
                work_sets_after=result_a.new_work_sets,
                is_deload=False,
                work_sets_growth_reason=result_a.work_sets_growth_reason,
            )
            grew_a = result_a.new_target > target_a or result_a.new_work_sets > work_sets_a
            stall_streak_a = 0 if grew_a else stall_streak_a + 1
            weak_streak_a = weak_streak_a + 1 if record.block_a.log.volume < prev_volume_a else 0
            prev_volume_a = record.block_a.log.volume
            target_a, work_sets_a = result_a.new_target, result_a.new_work_sets

        if record.block_b.is_heavy:
            block_b_assignment = BlockAssignment(
                log=record.block_b.log,
                target_before=target_b,
                target_after=target_b,
                equipment_changed=False,
                equipment_type=record.block_b.equipment_type,
                equipment_value=record.block_b.equipment_value,
                equipment_item_id=record.block_b.equipment_item_id,
                transition_failed=record.block_b.transition_failed,
                is_heavy=True,
            )
        else:
            result_b = recalculate_target(
                STRENGTH_BLOCK, target_b, record.block_b.log.working_reps, record.block_b.log.max_reps,
                record.block_b.log.volume, prev_volume_b,
                consecutive_weak_before=weak_streak_b,
            )
            block_b_assignment = BlockAssignment(
                log=record.block_b.log,
                target_before=target_b,
                target_after=result_b.new_target,
                equipment_changed=result_b.equipment_changed,
                equipment_type=record.block_b.equipment_type,
                equipment_value=record.block_b.equipment_value,
                equipment_item_id=record.block_b.equipment_item_id,
                transition_failed=record.block_b.transition_failed,
                is_heavy=False,
            )
            target_b = result_b.new_target
            weak_streak_b = weak_streak_b + 1 if record.block_b.log.volume < prev_volume_b else 0
            prev_volume_b = record.block_b.log.volume

        updated.append(
            WorkoutRecord(
                performed_at=record.performed_at,
                block_a=block_a_assignment,
                block_b=block_b_assignment,
                comment=record.comment,
                workout_set_id=record.workout_set_id,
                exercise_type=record.exercise_type,
            )
        )

    return updated
