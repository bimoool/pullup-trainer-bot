"""Live Engine v2: engine state columns + append-only session_events (issue #306)

Revision ID: a9e6c3d1f5b7
Revises: f4c1a7e9b3d2
Create Date: 2026-10-10 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a9e6c3d1f5b7'
down_revision: str | None = 'f4c1a7e9b3d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DOMAIN-V2 Wave 2 (docs/domain/LIVE_ENGINE_V2.md §1, MIGRATION_V2.md §6). Строится на миграции #307
# (f4c1a7e9b3d2): engine_version там уже есть; здесь — только колонки движка и журнал событий.
#
# Expand — только аддитивно, без backfill: сессии, начатые до выкладки (engine_version = 1 или NULL),
# не трогаются и доживают на движке v1. Старый код этих колонок/таблицы не знает: всё NULLABLE, его
# INSERT/UPDATE работают как раньше.
#   training_sessions.engine_plan   JSONB — неизменяемый план движка (из PrescriptionSnapshot при старте);
#   training_sessions.engine_state  JSONB — кэш свёртки session_events (LIVE §1);
#   training_sessions.engine_status — active | completed | cancelled (CHECK; строка, не PG enum: отмена
#     не добавляет значение в mp_session_status — старый образ при откате не упадёт на чтении, §11
#     TRAINING_SESSION_V2);
#   session_events — append-only журнал: (session_id, seq) уникален, client_event_id уникален
#     (идемпотентность офлайн-повтора), server_at — момент применения (зажатый client_at / дедлайн).
#
# downgrade снимает ровно это: теряются журнал событий и состояние движка v2; сами сессии, их подходы,
# длительность и кредит плана остаются (старый код видит незавершённую v2-сессию как обычную
# STARTED-сессию v1 — её можно завершить старым путём).


def upgrade() -> None:
    op.add_column('training_sessions', sa.Column('engine_plan', postgresql.JSONB(), nullable=True))
    op.add_column('training_sessions', sa.Column('engine_state', postgresql.JSONB(), nullable=True))
    op.add_column('training_sessions', sa.Column('engine_status', sa.String(16), nullable=True))
    op.create_check_constraint(
        'ck_training_sessions_engine_status', 'training_sessions',
        "engine_status IS NULL OR engine_status IN ('active', 'completed', 'cancelled')",
    )
    op.create_table(
        'session_events',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column(
            'session_id', sa.BigInteger(), sa.ForeignKey('training_sessions.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('client_event_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('type', sa.String(32), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('client_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('server_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.UniqueConstraint('session_id', 'seq', name='uq_session_events_session_seq'),
        sa.UniqueConstraint('client_event_id', name='uq_session_events_client_event_id'),
        sa.CheckConstraint("outcome IN ('applied', 'noop')", name='ck_session_events_outcome'),
    )


def downgrade() -> None:
    op.drop_table('session_events')
    op.drop_constraint('ck_training_sessions_engine_status', 'training_sessions', type_='check')
    op.drop_column('training_sessions', 'engine_status')
    op.drop_column('training_sessions', 'engine_state')
    op.drop_column('training_sessions', 'engine_plan')
