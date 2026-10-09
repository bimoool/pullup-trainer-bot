"""TrainingSession v2: explicit sources, identity, prescription snapshot, duration model (issue #307)

Revision ID: f4c1a7e9b3d2
Revises: d8a3c6f1e2b4
Create Date: 2026-10-09 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f4c1a7e9b3d2'
down_revision: str | None = 'd8a3c6f1e2b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DOMAIN-V2 Wave 3a (docs/domain/TRAINING_SESSION_V2.md §2–§4, MIGRATION_V2.md §1, §3). Это ОДНА
# миграция колонок training_sessions, на которой строится Wave 2 (#306 добавит только колонки движка и
# session_events после неё).
#
# Expand — только аддитивно; старый код продолжает работать (его INSERT новых колонок не знает: всё
# NULLABLE или с server_default). Ни одна колонка не переименована, не сменила тип и не удалена;
# workout_snapshot (v1-снимок живого движка) остаётся как есть и только читается.
#   training_sessions: kind, source_v2, origin, workout_definition_id, workout_definition_version_id,
#     prescription_snapshot, program_inclusion_id, started_at, ended_at, duration_source, timezone,
#     distance_meters, spacing_violation, revision, engine_version, superseded_by_id,
#     identity_recovered_by;
#   session_blocks: block_key, status, ended_at;
#   set_targets: kind;
#   set_logs: round_index, status (server_default 'performed' — каждая существующая строка и есть
#     выполненный подход), load_actual.
# superseded_by_id заводится здесь (одна миграция сессии), заполняет его сведение legacy-истории —
# Wave 3b (#308, MIGRATION_V2 §4).
#
# Backfill — детерминированный литеральный SQL (из app.* ничего не импортируется: правка рантайма не
# меняет того, что пишет эта ревизия); каждый UPDATE ограничен «... IS NULL», повторный прогон = 0
# изменений:
#   1. kind = external_activity при activity_type, иначе strength;
#   2. origin = legacy_elective (source = elective), legacy_backfill (отпечаток копии legacy Workout —
#      тот же предикат, что TrainingSessionRepository._backfilled_fingerprint на 2026-10-09), иначе native;
#   3. source_v2 — таблица MIGRATION_V2 §3 (app.domain.training_session_v2.legacy_source_v2):
#      backdated без снимка — manual_custom; восстановление идентичности по ТОЧНОМУ совпадению
#      (→ manual_existing_workout) делает scripts/backfill_training_session_v2.py, не эта ревизия;
#   4. длительность: активность — её значение (entered); остальные — completed_at − performed_at в окне
#      [60 с, 6 ч] (measured) — ровно то, что аналитика уже показывала минутами; иначе unknown (никогда
#      не 0 и не выдумка);
#   5. живые сессии (client_session_id): started_at = performed_at, ended_at = completed_at,
#      engine_version = 1;
#   6. workout_definition_id: из v1-снимка (workout_snapshot.workout_id), если такой Complex есть; иначе у
#      засчитанной сессии плана — PlanItem.workout_definition_id; program_inclusion_id — у засчитанной
#      сессии курса из её PlanItem. workout_definition_version_id истории НЕ восстанавливается (какая
#      версия была текущей тогда — неизвестно; содержание сохранено снимком).
# Синтезированный prescription_snapshot (S4) и восстановление идентичности — скрипт (им нужны имена
# упражнений и сравнение упорядоченных списков; dry-run по умолчанию, apply-again = 0).
# Подписки, доступ к программам, plan_items и прогрессия не читаются и не пишутся (MIGRATION_V2 §7).
#
# downgrade снимает ровно добавленное этой ревизией: теряются явный источник/происхождение, ссылка на
# определение/версию, prescription_snapshot, модель длительности (duration_seconds остаётся: колонка
# старше этой ревизии; заполненное здесь значение старый код читает как длительность — те же числа, что
# он сам вычислял), ревизии правок, статусы подходов. Сессии, их подходы и кредит плана не тронуты.
# Повторный upgrade восстанавливает backfill 1–6; синтез снимков — повторный прогон скрипта.

_SESSION_COLUMNS = (
    'identity_recovered_by', 'superseded_by_id', 'engine_version', 'revision', 'spacing_violation',
    'distance_meters', 'timezone', 'duration_source', 'ended_at', 'started_at', 'program_inclusion_id',
    'prescription_snapshot', 'workout_definition_version_id', 'workout_definition_id', 'origin',
    'source_v2', 'kind',
)


def upgrade() -> None:
    op.add_column('training_sessions', sa.Column('kind', sa.String(32), nullable=True))
    op.add_column('training_sessions', sa.Column('source_v2', sa.String(32), nullable=True))
    op.add_column('training_sessions', sa.Column('origin', sa.String(32), nullable=True))
    op.add_column(
        'training_sessions',
        sa.Column(
            'workout_definition_id', sa.BigInteger(), sa.ForeignKey('complexes.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.add_column(
        'training_sessions',
        sa.Column(
            'workout_definition_version_id', sa.BigInteger(),
            sa.ForeignKey('workout_definition_versions.id', ondelete='SET NULL'), nullable=True,
        ),
    )
    op.add_column('training_sessions', sa.Column('prescription_snapshot', postgresql.JSONB(), nullable=True))
    op.add_column(
        'training_sessions',
        sa.Column(
            'program_inclusion_id', sa.BigInteger(), sa.ForeignKey('program_inclusions.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.add_column('training_sessions', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('training_sessions', sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('training_sessions', sa.Column('duration_source', sa.String(16), nullable=True))
    op.add_column('training_sessions', sa.Column('timezone', sa.String(64), nullable=True))
    op.add_column('training_sessions', sa.Column('distance_meters', sa.Integer(), nullable=True))
    op.add_column(
        'training_sessions',
        sa.Column('spacing_violation', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column('training_sessions', sa.Column('revision', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('training_sessions', sa.Column('engine_version', sa.SmallInteger(), nullable=True))
    op.add_column(
        'training_sessions',
        sa.Column(
            'superseded_by_id', sa.BigInteger(), sa.ForeignKey('training_sessions.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.add_column('training_sessions', sa.Column('identity_recovered_by', sa.String(32), nullable=True))
    op.create_index(
        'ix_training_sessions_user_workout_definition', 'training_sessions', ['user_id', 'workout_definition_id'],
    )
    op.create_check_constraint(
        'ck_training_sessions_kind', 'training_sessions', "kind IS NULL OR kind IN ('strength', 'external_activity')",
    )
    op.create_check_constraint(
        'ck_training_sessions_source_v2', 'training_sessions',
        "source_v2 IS NULL OR source_v2 IN ('planned_live', 'direct_live', 'manual_existing_workout', "
        "'manual_custom', 'external_activity')",
    )
    op.create_check_constraint(
        'ck_training_sessions_origin', 'training_sessions',
        "origin IS NULL OR origin IN ('native', 'legacy_backfill', 'legacy_elective')",
    )
    op.create_check_constraint(
        'ck_training_sessions_duration_source', 'training_sessions',
        "duration_source IS NULL OR duration_source IN ('measured', 'entered', 'unknown')",
    )

    op.add_column('session_blocks', sa.Column('block_key', sa.String(64), nullable=True))
    op.add_column('session_blocks', sa.Column('status', sa.String(16), nullable=True))
    op.add_column('session_blocks', sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('set_targets', sa.Column('kind', sa.String(16), nullable=True))
    op.add_column('set_logs', sa.Column('round_index', sa.SmallInteger(), nullable=True))
    op.add_column(
        'set_logs', sa.Column('status', sa.String(16), nullable=False, server_default='performed'),
    )
    op.add_column('set_logs', sa.Column('load_actual', postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        'ck_set_logs_status', 'set_logs', "status IN ('performed', 'not_performed')",
    )

    _backfill()


def _backfill() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE training_sessions SET kind = CASE WHEN activity_type IS NOT NULL "
        "THEN 'external_activity' ELSE 'strength' END WHERE kind IS NULL"
    ))
    conn.execute(sa.text(
        "UPDATE training_sessions SET origin = 'legacy_elective' WHERE origin IS NULL AND source = 'elective'"
    ))
    conn.execute(sa.text(
        "UPDATE training_sessions t SET origin = 'legacy_backfill' "
        "WHERE t.origin IS NULL AND t.status = 'completed' AND t.source IN ('plan', 'freeform', 'backdated') "
        "AND t.client_session_id IS NULL AND t.workout_snapshot IS NULL AND t.activity_type IS NULL "
        "AND t.plan_item_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM session_plan_items spi WHERE spi.session_id = t.id) "
        "AND EXISTS (SELECT 1 FROM session_blocks b JOIN exercises e ON e.id = b.exercise_id "
        "            WHERE b.session_id = t.id AND b.order_index = 0 AND e.category = 'pull_ups' "
        "            AND e.subcategory = 'block_a' AND e.source_type = 'system' AND e.owner_user_id IS NULL)"
    ))
    conn.execute(sa.text("UPDATE training_sessions SET origin = 'native' WHERE origin IS NULL"))

    conn.execute(sa.text(
        "UPDATE training_sessions SET source_v2 = CASE "
        "  WHEN activity_type IS NOT NULL THEN 'external_activity' "
        "  WHEN source = 'plan' THEN 'planned_live' "
        "  WHEN source = 'elective' THEN 'manual_existing_workout' "
        "  WHEN source = 'freeform' AND (workout_snapshot IS NOT NULL OR client_session_id IS NOT NULL) "
        "    THEN 'direct_live' "
        "  WHEN source = 'freeform' THEN 'manual_custom' "
        "  WHEN source = 'backdated' AND workout_snapshot IS NOT NULL THEN 'manual_existing_workout' "
        "  ELSE 'manual_custom' END "
        "WHERE source_v2 IS NULL"
    ))

    conn.execute(sa.text(
        "UPDATE training_sessions SET duration_source = CASE "
        "  WHEN activity_type IS NOT NULL AND duration_seconds IS NOT NULL THEN 'entered' "
        "  WHEN activity_type IS NOT NULL THEN 'unknown' "
        "  WHEN duration_seconds IS NOT NULL THEN 'measured' "
        "  WHEN completed_at IS NOT NULL "
        "   AND EXTRACT(EPOCH FROM (completed_at - performed_at)) BETWEEN 60 AND 21600 THEN 'measured' "
        "  ELSE 'unknown' END, "
        "duration_seconds = CASE "
        "  WHEN activity_type IS NULL AND duration_seconds IS NULL AND completed_at IS NOT NULL "
        "   AND EXTRACT(EPOCH FROM (completed_at - performed_at)) BETWEEN 60 AND 21600 "
        "  THEN FLOOR(EXTRACT(EPOCH FROM (completed_at - performed_at)))::integer "
        "  ELSE duration_seconds END "
        "WHERE duration_source IS NULL"
    ))
    conn.execute(sa.text(
        "UPDATE training_sessions SET started_at = performed_at, ended_at = completed_at, engine_version = 1 "
        "WHERE client_session_id IS NOT NULL AND engine_version IS NULL"
    ))

    conn.execute(sa.text(
        "UPDATE training_sessions t SET workout_definition_id = c.id "
        "FROM complexes c "
        "WHERE t.workout_definition_id IS NULL AND t.workout_snapshot IS NOT NULL "
        "AND (t.workout_snapshot->>'workout_id') ~ '^[0-9]+$' "
        "AND c.id = (t.workout_snapshot->>'workout_id')::bigint"
    ))
    conn.execute(sa.text(
        "UPDATE training_sessions t SET "
        "workout_definition_id = COALESCE(t.workout_definition_id, p.workout_definition_id), "
        "program_inclusion_id = COALESCE(t.program_inclusion_id, p.program_inclusion_id) "
        "FROM plan_items p "
        "WHERE p.id = t.plan_item_id "
        "AND ((t.workout_definition_id IS NULL AND p.workout_definition_id IS NOT NULL) "
        "     OR (t.program_inclusion_id IS NULL AND p.program_inclusion_id IS NOT NULL))"
    ))


def downgrade() -> None:
    op.drop_constraint('ck_set_logs_status', 'set_logs', type_='check')
    for column in ('load_actual', 'status', 'round_index'):
        op.drop_column('set_logs', column)
    op.drop_column('set_targets', 'kind')
    for column in ('ended_at', 'status', 'block_key'):
        op.drop_column('session_blocks', column)
    for name in (
        'ck_training_sessions_duration_source', 'ck_training_sessions_origin', 'ck_training_sessions_source_v2',
        'ck_training_sessions_kind',
    ):
        op.drop_constraint(name, 'training_sessions', type_='check')
    op.drop_index('ix_training_sessions_user_workout_definition', table_name='training_sessions')
    for column in _SESSION_COLUMNS:
        op.drop_column('training_sessions', column)
