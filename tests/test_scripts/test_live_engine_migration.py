"""Deploy-level репетиция ревизии a9e6c3d1f5b7 (issue #306, MIGRATION_V2 §6, §8): аддитивно, без backfill,
сессии в полёте остаются на движке v1; downgrade → upgrade безопасен. Своя временная БД, alembic подпроцессом."""

import pytest
from sqlalchemy.exc import IntegrityError

from tests.test_scripts.test_program_plan_migration import _exec as _exec_async
from tests.test_scripts.test_system_content_migration import (
    _alembic,
    _run,
    _scalar,
    scratch_dsn,  # noqa: F401 — фикстура
)
from tests.test_scripts.test_training_session_v2_migration import _fingerprint

PRE_REVISION = "f4c1a7e9b3d2"
REVISION = "a9e6c3d1f5b7"

IN_FLIGHT = """
INSERT INTO users (id, telegram_id, timezone, subscription_status) VALUES (1101, 9101, 'UTC', 'trial');
INSERT INTO exercises (id, name, metric_type, category, source_type, owner_user_id) VALUES
 (7101, 'Отжимания', 'reps', 'user', 'user', 1101);
INSERT INTO training_sessions (id, user_id, source, status, performed_at, client_session_id, phase_name,
  phase_ends_at, engine_version, source_v2, kind, origin, started_at) VALUES
 (9101, 1101, 'freeform', 'started', now() - interval '3 minutes', '44444444-4444-4444-8444-444444444444',
  'rest', now() + interval '1 minute', 1, 'direct_live', 'strength', 'native', now() - interval '3 minutes'),
 (9102, 1101, 'freeform', 'completed', now() - interval '2 days', NULL, 'done', NULL, NULL,
  'manual_custom', 'strength', 'native', NULL);
INSERT INTO session_blocks (id, session_id, order_index, exercise_id) VALUES (8101, 9101, 0, 7101);
INSERT INTO set_logs (session_block_id, set_number, metric_type, value, unit, session_id, set_index) VALUES
 (8101, 1, 'reps', 10, 'reps', 9101, 0);
"""


def _exec(dsn: str, sql: str) -> None:
    _run(_exec_async(dsn, sql))


def test_fresh_install_single_head_creates_engine_schema(scratch_dsn):  # noqa: F811
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    assert ScriptDirectory.from_config(Config("alembic.ini")).get_heads() == [REVISION]
    _alembic(scratch_dsn, "upgrade", "head")
    assert _scalar(scratch_dsn, "SELECT version_num FROM alembic_version") == REVISION
    assert _scalar(scratch_dsn, "SELECT count(*) FROM session_events") == 0
    columns = _scalar(
        scratch_dsn,
        "SELECT string_agg(column_name, ',' ORDER BY column_name) FROM information_schema.columns "
        "WHERE table_name = 'training_sessions' AND column_name LIKE 'engine_%'",
    )
    assert columns == "engine_plan,engine_state,engine_status,engine_version"


def test_upgrade_keeps_in_flight_sessions_on_engine_v1_and_history_untouched(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", PRE_REVISION)
    _exec(scratch_dsn, IN_FLIGHT)
    before = _fingerprint(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", REVISION)
    assert _fingerprint(scratch_dsn) == before  # без backfill: ни сессии, ни подходы, ни кредит не тронуты
    assert _scalar(scratch_dsn, "SELECT engine_version FROM training_sessions WHERE id = 9101") == 1
    assert _scalar(
        scratch_dsn, "SELECT count(*) FROM training_sessions WHERE engine_plan IS NOT NULL OR engine_state IS NOT NULL "
        "OR engine_status IS NOT NULL",
    ) == 0
    # старый код (не знает новых колонок) по-прежнему вставляет сессию
    _exec(scratch_dsn, """INSERT INTO training_sessions (id, user_id, source, status, performed_at)
                          VALUES (9103, 1101, 'backdated', 'completed', now())""")
    assert _scalar(scratch_dsn, "SELECT count(*) FROM training_sessions") == 3


def test_check_constraints_and_unique_client_event_id(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", REVISION)
    _exec(scratch_dsn, IN_FLIGHT)
    _exec(scratch_dsn, """INSERT INTO session_events (session_id, seq, client_event_id, type, server_at, outcome)
                          VALUES (9101, 0, '55555555-5555-4555-8555-555555555555', 'pause', now(), 'applied')""")
    for bad in (
        "INSERT INTO session_events (session_id, seq, type, server_at, outcome) VALUES (9101, 0, 'x', now(), 'applied')",
        (
            "INSERT INTO session_events (session_id, seq, client_event_id, type, server_at, outcome) VALUES "
            "(9102, 0, '55555555-5555-4555-8555-555555555555', 'pause', now(), 'applied')"
        ),
        "INSERT INTO session_events (session_id, seq, type, server_at, outcome) VALUES (9101, 1, 'x', now(), 'maybe')",
        "UPDATE training_sessions SET engine_status = 'paused' WHERE id = 9101",
    ):
        with pytest.raises(IntegrityError):
            _exec(scratch_dsn, bad)


def test_downgrade_then_upgrade_is_safe(scratch_dsn):  # noqa: F811
    _alembic(scratch_dsn, "upgrade", REVISION)
    _exec(scratch_dsn, IN_FLIGHT)
    _exec(scratch_dsn, """UPDATE training_sessions SET engine_version = 2, engine_status = 'active',
                          engine_state = '{"status": "active"}', engine_plan = '{"blocks": []}' WHERE id = 9101;
                          INSERT INTO session_events (session_id, seq, type, server_at, outcome)
                          VALUES (9101, 0, 'start', now(), 'applied')""")
    before = _fingerprint(scratch_dsn)
    _alembic(scratch_dsn, "downgrade", PRE_REVISION)
    assert _fingerprint(scratch_dsn) == before  # сессии/подходы/кредит пережили откат схемы
    assert _scalar(scratch_dsn, "SELECT count(*) FROM information_schema.tables WHERE table_name = 'session_events'") == 0
    _alembic(scratch_dsn, "upgrade", REVISION)
    assert _scalar(scratch_dsn, "SELECT count(*) FROM session_events") == 0
    assert _fingerprint(scratch_dsn) == before
