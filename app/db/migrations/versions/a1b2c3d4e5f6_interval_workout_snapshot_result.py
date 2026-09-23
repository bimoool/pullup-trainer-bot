"""interval workout snapshot and result fields

Revision ID: a1b2c3d4e5f6
Revises: 5f6a7b8c9d0e
Create Date: 2026-09-22 17:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '5f6a7b8c9d0e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Phase B1 (issue #215) — Interval Workout Execution: два additive JSONB поля
# для interval workouts. NULL обязателен — legacy rows (все существующие
# сессии до этой миграции) не имеют ни workout_snapshot, ни result, только
# новый interval-путь будет их заполнять. Не добавляется execution_started_at
# колонка (вычисляется на лету как performed_at + GET_READY_SECONDS), не
# добавляется SessionPhase.WORK enum-значение (interval использует только
# существующие GET_READY/GO/REST/DONE), не добавляются отдельные записи
# WORK/REST на каждый цикл.


def upgrade() -> None:
    op.add_column('training_sessions', sa.Column('workout_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('session_blocks', sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('session_blocks', 'result')
    op.drop_column('training_sessions', 'workout_snapshot')
