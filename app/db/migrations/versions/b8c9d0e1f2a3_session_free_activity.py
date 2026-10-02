"""training_sessions.activity_type / duration_seconds (свободная активность, #263)

Revision ID: b8c9d0e1f2a3
Revises: a1b2c3d4e5f7
Create Date: 2026-10-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: str | None = 'a1b2c3d4e5f7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Аддитивно и совместимо со старым кодом: две nullable-колонки без default,
# backfill не нужен (заполняются только свободными активностями).


def upgrade() -> None:
    op.add_column('training_sessions', sa.Column('activity_type', sa.String(length=32), nullable=True))
    op.add_column('training_sessions', sa.Column('duration_seconds', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('training_sessions', 'duration_seconds')
    op.drop_column('training_sessions', 'activity_type')
