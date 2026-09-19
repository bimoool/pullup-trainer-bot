"""Чистая машина состояний фазы живой сессии (issue #165, продолжение
волны 3 — "сессия — live", раздел 11 docs/plan-and-specs.md): в состоянии
ACTIVE — цикл get_ready -> go -> rest по кругу на каждый подход внутри
блока, done — сессия завершена. Ни одного импорта aiogram/sqlalchemy
(проверяется `grep -rl "aiogram\\|sqlalchemy" app/domain/`, см. CLAUDE.md) —
сервисный слой (app.services.live_session) явно конвертирует
SessionPhaseName ниже в app.db.models_program.SessionPhase и обратно,
домен ничего не знает о схеме/ORM.

Датаклассы здесь offset-чистые (секунды, не datetime) — ни одного вызова
datetime.now() внутри: next_phase()/initial_phase() отдают "сколько секунд
от текущего момента длится фаза", вызывающий сервис сам прибавляет offset
к своему now() (тот же принцип "домен не знает времени выполнения", что и
у остального app/domain/ — ни один другой модуль здесь не вызывает
datetime.now())."""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.multi_program import MetricType

# Продуктовые константы (не научные факты — тот же принцип явного
# флагирования, что у app.domain.progression.recalculate_volume_block, см.
# CLAUDE.md): GET_READY_SECONDS — время на подготовку перед подходом,
# число выбрано для этой фичи "с потолка", не выверено на реальных
# тренировках. DEFAULT_REST_SECONDS — единственный источник длительности
# отдыха для блоков без собственной настройки: схема не несёт per-exercise
# отдых нигде, кроме ComplexItem.rest_seconds (который на этой волне ещё не
# проброшен в резолвер блоков сессии, см. app.services.live_session) —
# открытый, осознанно не закрытый пробел, а не "забыли".
GET_READY_SECONDS = 5
DEFAULT_REST_SECONDS = 90

# Единица измерения подхода "по умолчанию" для каждого MetricType — та же
# заглушка природы, что GET_READY_SECONDS/DEFAULT_REST_SECONDS выше:
# продуктовый выбор, не физический факт, применяется, когда более точного
# источника нет — SetTarget без ComplexItem.target_unit, или батч подходов
# живой сессии (app.db.repositories.training_sessions::upsert_set_logs_batch),
# который вообще не несёт unit в теле запроса. Схема не хранит per-exercise
# дефолтную единицу нигде — открытый, явно флагированный пробел (CLAUDE.md).
DEFAULT_UNIT_BY_METRIC_TYPE: dict[MetricType, str] = {
    MetricType.REPS: "reps",
    MetricType.TIME: "s",
    MetricType.WEIGHT: "kg",
    MetricType.ANGLE: "deg",
    MetricType.DISTANCE: "m",
}


class SessionPhaseName(StrEnum):
    """Независимая от app.db.models_program.SessionPhase копия тех же 4
    значений (домен не импортирует app.db, см. докстринг модуля выше) —
    сервисный слой конвертирует явно, а не полагается на совпадение имён."""

    GET_READY = "get_ready"
    GO = "go"
    REST = "rest"
    DONE = "done"


@dataclass(frozen=True)
class BlockPlan:
    """Единственное, что нужно чистой машине фаз про один блок сессии —
    число подходов. next_phase() не знает ни про упражнения, ни про
    цели/веса — только про то, сколько подходов пройти, прежде чем перейти
    к следующему блоку."""

    sets_count: int


@dataclass(frozen=True)
class PhaseState:
    """Текущая фаза + позиция в сессии. ends_at_offset_seconds — секунд от
    "сейчас" до конца фазы, None для фаз без таймера (см. next_phase).
    Вызывающий сервис делает `datetime.now(UTC) + timedelta(seconds=...)`
    сам — этот датакласс timezone/datetime не видит."""

    phase_name: SessionPhaseName
    block_index: int
    set_number: int
    ends_at_offset_seconds: int | None


def initial_phase(blocks: list[BlockPlan]) -> PhaseState:
    """Старт живой сессии — get_ready первого подхода первого блока.

    Пустой blocks — защитный случай (по продуктовой логике сервис не
    должен звать start_session с пустым списком резолвнутых блоков), но
    домен не должен падать на нём: сразу done вместо IndexError ниже по
    next_phase()."""
    if not blocks:
        return PhaseState(phase_name=SessionPhaseName.DONE, block_index=0, set_number=1, ends_at_offset_seconds=None)
    return PhaseState(
        phase_name=SessionPhaseName.GET_READY, block_index=0, set_number=1,
        ends_at_offset_seconds=GET_READY_SECONDS,
    )


def next_phase(
    current: PhaseState, blocks: list[BlockPlan], *, rest_seconds: int = DEFAULT_REST_SECONDS,
) -> PhaseState:
    """Единственное место, где считается следующая фаза (тот же приём, что
    StepProgressionStrategy.preview физически вызывающий apply,
    app.domain.progression_strategy) — сервис и тесты вызывают именно эту
    функцию, не дублируют переходы отдельно.

    get_ready -> go: БЕЗ таймера (ends_at_offset_seconds=None) —
    осознанное упрощение: схема не несёт per-set длительность/целевое
    число повторов вне ComplexItem (см. докстринг модуля, открытый пробел,
    не молчаливое поведение) — пользователь логирует подход и вызывает
    phase/next сам, когда закончил, не по обратному отсчёту.

    go -> следующий шаг:
      - последний подход последнего блока -> done;
      - последний подход НЕпоследнего блока -> get_ready первого подхода
        следующего блока;
      - иначе -> rest этого же подхода/блока.

    rest -> get_ready СЛЕДУЮЩЕГО подхода (set_number+1) того же блока.

    done -> done: идемпотентно. Вызывающий код не должен звать next_phase
    после done (клиент останавливает цикл), но если позвал — не падаем,
    просто возвращаем то же состояние."""
    if current.phase_name == SessionPhaseName.DONE:
        return current

    if not blocks or current.block_index >= len(blocks):
        # Рассинхрон state/blocks (не должен происходить в норме) — done
        # вместо IndexError, тот же защитный принцип, что и initial_phase.
        return PhaseState(
            phase_name=SessionPhaseName.DONE, block_index=current.block_index,
            set_number=current.set_number, ends_at_offset_seconds=None,
        )

    block = blocks[current.block_index]

    if current.phase_name == SessionPhaseName.GET_READY:
        return PhaseState(
            phase_name=SessionPhaseName.GO, block_index=current.block_index, set_number=current.set_number,
            ends_at_offset_seconds=None,
        )

    if current.phase_name == SessionPhaseName.GO:
        is_last_set_of_block = current.set_number >= block.sets_count
        is_last_block = current.block_index >= len(blocks) - 1
        if is_last_set_of_block and is_last_block:
            return PhaseState(
                phase_name=SessionPhaseName.DONE, block_index=current.block_index,
                set_number=current.set_number, ends_at_offset_seconds=None,
            )
        if is_last_set_of_block:
            return PhaseState(
                phase_name=SessionPhaseName.GET_READY, block_index=current.block_index + 1, set_number=1,
                ends_at_offset_seconds=GET_READY_SECONDS,
            )
        return PhaseState(
            phase_name=SessionPhaseName.REST, block_index=current.block_index, set_number=current.set_number,
            ends_at_offset_seconds=rest_seconds,
        )

    # current.phase_name == SessionPhaseName.REST
    return PhaseState(
        phase_name=SessionPhaseName.GET_READY, block_index=current.block_index, set_number=current.set_number + 1,
        ends_at_offset_seconds=GET_READY_SECONDS,
    )
