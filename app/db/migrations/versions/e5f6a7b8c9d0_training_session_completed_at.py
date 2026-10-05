"""training_sessions.completed_at

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-01 23:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = 'd4e5f6a7b8c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Аддитивно и совместимо со старым кодом: nullable-колонка без default.
# Backfill НЕ делается — у старых сессий момент завершения неизвестен, они
# считаются тренировками, но не минутами (CRIMPD analytics, #259).


def upgrade() -> None:
    op.add_column('training_sessions', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('training_sessions', 'completed_at')
