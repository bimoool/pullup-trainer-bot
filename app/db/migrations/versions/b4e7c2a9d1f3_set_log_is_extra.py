"""set_logs.is_extra — extra set beyond the prescribed plan

Revision ID: b4e7c2a9d1f3
Revises: a1b2c3d4e5f7
Create Date: 2026-10-02 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b4e7c2a9d1f3'
down_revision: str | None = 'a1b2c3d4e5f7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Аддитивно (issue #264): NOT NULL с server_default=false — старый код колонку не
# знает и не пишет, существующие строки получают false.


def upgrade() -> None:
    op.add_column('set_logs', sa.Column('is_extra', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('set_logs', 'is_extra')
