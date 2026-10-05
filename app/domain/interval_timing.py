"""Чистая timing model для interval workout execution (Phase B1, issue #215)
— server-authoritative absolute timing, полностью вычисляемое, ничего не
пишется в БД на каждый цикл. Ни одного импорта datetime.now()/aiogram/
sqlalchemy (домен не знает времени выполнения, проверяется буквально —
`grep -rl "datetime.now\\|aiogram\\|sqlalchemy" app/domain/`, см. CLAUDE.md).

Параметры offset-чистые: `now` передаётся явно вызывающим сервисом, домен
сам не вызывает datetime.now() — тот же принцип, что
app.domain.live_session (см. докстринг там же). Все расчёты — в секундах
от execution_started_at/total_end_at, никаких datetime внутри домена."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import floor

from app.domain.live_session import GET_READY_SECONDS


class IntervalPhase(StrEnum):
    """Фаза interval workout — чистый датакласс-подобный StrEnum, независимый
    от app.db.models_program.SessionPhase (домен не импортирует app.db, см.
    CLAUDE.md). Сервисный слой явно конвертирует между ними, где нужно."""

    GET_READY = "get_ready"
    WORK = "work"
    REST = "rest"
    DONE = "done"


@dataclass(frozen=True)
class IntervalTiming:
    """Resolved timing model для одного interval workout — единственный
    источник правды для фазы/phase_ends_at/completed_cycles. Вычисляется
    заново на каждый запрос (не персистится в БД), детерминирован по:
    - execution_started_at (performed_at + GET_READY_SECONDS)
    - protocol (total_duration_seconds, work_seconds, rest_seconds)
    - now (явный параметр, переданный вызывающим сервисом)

    phase_ends_at — UTC datetime конца ТЕКУЩЕЙ фазы (не следующей), None
    только для done (сессия завершена, следующего конца фазы нет)."""

    execution_started_at: datetime
    total_end_at: datetime
    phase: IntervalPhase
    phase_ends_at: datetime | None
    total_duration_seconds: int
    work_seconds: int
    rest_seconds: int
    completed_cycles: int


def execution_started_at(performed_at: datetime) -> datetime:
    """НЕ персистится отдельной колонкой (по контрактному решению Phase B1,
    см. issue #215, раздел 0) — вычисляется детерминированно при каждом
    чтении. performed_at уже существует, пишется один раз в start_session."""
    return performed_at + timedelta(seconds=GET_READY_SECONDS)


def calculate_completed_cycles(
    *,
    elapsed_seconds: float,
    total_duration_seconds: int,
    work_seconds: int,
    rest_seconds: int,
) -> int:
    """Число полностью завершённых WORK-фаз (граница конца WORK —
    включительно). elapsed_seconds может быть дробным (реальный offset от
    datetime.now()), результат всегда int — floor на промежуточном шаге.

    Обязательные тестовые кейсы (см. issue #215, раздел 0):
    - 180/10/20 → 6 (ровно 6 полных циклов, 180 секунд)
    - 15/10/20 → 1 (один подход на максимум завершён до первого REST)
    - 5/10/20 → 0 (до конца первого WORK ещё не дошли)
    - 30/10/20 → 1 (один full цикл WORK+REST)
    - 40/10/20 → 2 (два полных цикла, второй REST не полный)"""
    elapsed_capped = min(elapsed_seconds, total_duration_seconds)
    cycle_duration = work_seconds + rest_seconds

    if elapsed_capped < work_seconds:
        return 0

    # floor((elapsed - work) / cycle) + 1 — первый подход на максимум засчитан
    # сразу по завершении (включительно), каждый следующий — по завершении
    # следующего WORK (не REST).
    return floor((elapsed_capped - work_seconds) / cycle_duration) + 1


def compute_interval_timing(
    *,
    performed_at: datetime,
    now: datetime,
    total_duration_seconds: int,
    work_seconds: int,
    rest_seconds: int,
) -> IntervalTiming:
    """Единственная публичная функция модуля — вычисляет полное состояние
    interval workout на момент `now`. Вызывается на каждый GET active/list
    (не персистится в БД), детерминирован по входным параметрам.

    Контрактные решения Phase B1 (см. issue #215, раздел 0):
    - execution_started_at вычисляется, не хранится
    - phase/phase_ends_at вычисляются на лету по модулю от elapsed
    - completed_cycles — по формуле выше, не по счётчику в БД

    Timing model:
        total_end_at = execution_started_at + total_duration_seconds
        elapsed = now - execution_started_at
        cycle_duration = work_seconds + rest_seconds
        position = elapsed % cycle_duration

        if now < execution_started_at: phase = get_ready
        elif now >= total_end_at: phase = done
        elif position < work_seconds: phase = work
        else: phase = rest

    phase_ends_at для вычисляемых фаз:
        get_ready: execution_started_at
        work: min(start_of_current_work + work_seconds, total_end_at)
        rest: min(start_of_current_rest + rest_seconds, total_end_at)
        done: total_end_at (или None по API-контракту — покрыть тестом)"""
    exec_start = execution_started_at(performed_at)
    total_end = exec_start + timedelta(seconds=total_duration_seconds)
    elapsed = (now - exec_start).total_seconds()
    cycle_duration = work_seconds + rest_seconds

    # Определение фазы
    if now < exec_start:
        phase = IntervalPhase.GET_READY
        phase_ends = exec_start
    elif now >= total_end:
        phase = IntervalPhase.DONE
        phase_ends = None  # done не имеет конца фазы (терминальное состояние)
    else:
        position = elapsed % cycle_duration
        if position < work_seconds:
            phase = IntervalPhase.WORK
            # start_of_current_work = exec_start + floor(elapsed / cycle) * cycle
            cycle_index = floor(elapsed / cycle_duration)
            start_of_current_work = exec_start + timedelta(seconds=cycle_index * cycle_duration)
            # truncated final WORK — не может выйти за total_end
            phase_ends = min(start_of_current_work + timedelta(seconds=work_seconds), total_end)
        else:
            phase = IntervalPhase.REST
            cycle_index = floor(elapsed / cycle_duration)
            start_of_current_rest = exec_start + timedelta(seconds=cycle_index * cycle_duration + work_seconds)
            # truncated final REST — не может выйти за total_end
            phase_ends = min(start_of_current_rest + timedelta(seconds=rest_seconds), total_end)

    completed = calculate_completed_cycles(
        elapsed_seconds=elapsed,
        total_duration_seconds=total_duration_seconds,
        work_seconds=work_seconds,
        rest_seconds=rest_seconds,
    )

    return IntervalTiming(
        execution_started_at=exec_start,
        total_end_at=total_end,
        phase=phase,
        phase_ends_at=phase_ends,
        total_duration_seconds=total_duration_seconds,
        work_seconds=work_seconds,
        rest_seconds=rest_seconds,
        completed_cycles=completed,
    )
