"""leaderboard display name

Revision ID: a7c1e4f8b3d2
Revises: f1a2b3c4d5e6
Create Date: 2026-09-06 06:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a7c1e4f8b3d2'
down_revision: str | None = 'f1a2b3c4d5e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('leaderboard_display_name', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'leaderboard_display_name')
