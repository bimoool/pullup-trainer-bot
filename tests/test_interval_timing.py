"""Domain tests для interval timing model (Phase B1, issue #215) — чистые
unit-тесты без БД/aiogram, offset-driven (explicit now parameter), покрывают
все обязательные кейсы из контракта Phase B1:

- get_ready до execution_started_at
- work start exact boundary
- work→rest boundary
- rest→work boundary
- total deadline
- truncated final WORK
- truncated final REST
- все 5 `completed_cycles` кейсов
- расчёт `phase_ends_at` для каждой фазы
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.interval_timing import IntervalPhase, calculate_completed_cycles, compute_interval_timing


class TestCalculateCompletedCycles:
    """Обязательные тестовые кейсы из контракта Phase B1 (issue #215, раздел 0)."""

    def test_180_10_20_gives_6_cycles(self):
        """180 сек total, 10 work, 20 rest → ровно 6 полных циклов."""
        result = calculate_completed_cycles(
            elapsed_seconds=180, total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert result == 6

    def test_15_10_20_gives_1_cycle(self):
        """15 сек elapsed (10 work + 5 rest), один подход на максимум завершён до первого REST."""
        result = calculate_completed_cycles(
            elapsed_seconds=15, total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert result == 1

    def test_5_10_20_gives_0_cycles(self):
        """5 сек elapsed, до конца первого WORK ещё не дошли."""
        result = calculate_completed_cycles(
            elapsed_seconds=5, total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert result == 0

    def test_30_10_20_gives_1_cycle(self):
        """30 сек elapsed (один full цикл WORK+REST)."""
        result = calculate_completed_cycles(
            elapsed_seconds=30, total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert result == 1

    def test_40_10_20_gives_2_cycles(self):
        """40 сек elapsed (два полных цикла, второй REST не полный)."""
        result = calculate_completed_cycles(
            elapsed_seconds=40, total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert result == 2

    def test_elapsed_exceeds_total_capped(self):
        """elapsed > total_duration — клэмпится к total, не превышает."""
        result = calculate_completed_cycles(
            elapsed_seconds=300, total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert result == 6  # 180 total → 6 циклов, не 300


class TestComputeIntervalTiming:
    """Фазовые переходы, phase_ends_at, truncated final WORK/REST."""

    def test_get_ready_before_execution_starts(self):
        """До execution_started_at: phase=get_ready, phase_ends_at=execution_started_at."""
        performed_at = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)
        now = performed_at + timedelta(seconds=2)  # GET_READY_SECONDS=5, ещё не кончился

        timing = compute_interval_timing(
            performed_at=performed_at, now=now,
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )

        assert timing.phase == IntervalPhase.GET_READY
        assert timing.execution_started_at == performed_at + timedelta(seconds=5)
        assert timing.phase_ends_at == timing.execution_started_at
        assert timing.completed_cycles == 0

    def test_work_start_exact_boundary(self):
        """Ровно на execution_started_at: phase=work (первый цикл начинается)."""
        performed_at = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)
        now = performed_at + timedelta(seconds=5)  # execution_started_at

        timing = compute_interval_timing(
            performed_at=performed_at, now=now,
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )

        assert timing.phase == IntervalPhase.WORK
        assert timing.completed_cycles == 0

    def test_work_to_rest_boundary(self):
        """На границе work→rest (execution_started_at + work_seconds): phase=rest."""
        performed_at = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)
        now = performed_at + timedelta(seconds=5 + 10)  # конец первого WORK

        timing = compute_interval_timing(
            performed_at=performed_at, now=now,
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )

        assert timing.phase == IntervalPhase.REST
        assert timing.completed_cycles == 1

    def test_rest_to_work_boundary(self):
        """На границе rest→work (конец первого REST): phase=work (второй цикл)."""
        performed_at = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)
        now = performed_at + timedelta(seconds=5 + 10 + 20)  # конец первого REST

        timing = compute_interval_timing(
            performed_at=performed_at, now=now,
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )

        assert timing.phase == IntervalPhase.WORK
        assert timing.completed_cycles == 1  # первый завершён

    def test_total_deadline_exact(self):
        """Ровно на total_end_at: phase=done."""
        performed_at = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)
        now = performed_at + timedelta(seconds=5 + 180)  # total_end_at

        timing = compute_interval_timing(
            performed_at=performed_at, now=now,
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )

        assert timing.phase == IntervalPhase.DONE
        assert timing.phase_ends_at is None  # done не имеет конца фазы
        assert timing.completed_cycles == 6

    def test_truncated_final_work(self):
        """Финальный WORK короче, чем work_seconds (total кончается посреди WORK)."""
        performed_at = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)
        # total=25: 5+10 (work) +10 (rest) → 5 секунд второго WORK, не 10
        now = performed_at + timedelta(seconds=5 + 22)

        timing = compute_interval_timing(
            performed_at=performed_at, now=now,
            total_duration_seconds=25, work_seconds=10, rest_seconds=10,
        )

        assert timing.phase == IntervalPhase.WORK
        # phase_ends_at не должен превышать total_end_at
        assert timing.phase_ends_at == timing.total_end_at
        assert timing.completed_cycles == 1  # первый завершён, второй не полный

    def test_truncated_final_rest(self):
        """Финальный REST короче, чем rest_seconds (total кончается посреди REST)."""
        performed_at = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)
        # total=25: 5+10 (work) +10 (rest) +5 секунд второго REST, не 10
        now = performed_at + timedelta(seconds=5 + 23)

        timing = compute_interval_timing(
            performed_at=performed_at, now=now,
            total_duration_seconds=25, work_seconds=10, rest_seconds=10,
        )

        assert timing.phase == IntervalPhase.REST
        assert timing.phase_ends_at == timing.total_end_at
        assert timing.completed_cycles == 1

    def test_phase_ends_at_for_each_phase(self):
        """Проверка, что phase_ends_at корректен для всех фаз."""
        performed_at = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)

        # get_ready
        timing = compute_interval_timing(
            performed_at=performed_at, now=performed_at + timedelta(seconds=2),
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert timing.phase_ends_at == performed_at + timedelta(seconds=5)

        # work
        timing = compute_interval_timing(
            performed_at=performed_at, now=performed_at + timedelta(seconds=7),
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert timing.phase_ends_at == performed_at + timedelta(seconds=5 + 10)

        # rest
        timing = compute_interval_timing(
            performed_at=performed_at, now=performed_at + timedelta(seconds=17),
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert timing.phase_ends_at == performed_at + timedelta(seconds=5 + 10 + 20)

        # done
        timing = compute_interval_timing(
            performed_at=performed_at, now=performed_at + timedelta(seconds=200),
            total_duration_seconds=180, work_seconds=10, rest_seconds=20,
        )
        assert timing.phase_ends_at is None  # терминальная фаза
