"""complexes.archived_at (soft delete of user workouts)

Revision ID: a1b2c3d4e5f7
Revises: f6a7b8c9d0e1
Create Date: 2026-10-02 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f7'
down_revision: str | None = 'f6a7b8c9d0e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Issue #261 — nullable-колонка, старый код её не читает и не пишет (аддитивно).


def upgrade() -> None:
    op.add_column('complexes', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('complexes', 'archived_at')
