"""weekly digests

Revision ID: 48eccea08c8b
Revises: e2c7a4f19d3b
Create Date: 2026-08-24 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '48eccea08c8b'
down_revision: str | None = 'e2c7a4f19d3b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'weekly_digests',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('recipients_count', sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_weekly_digests_sent_at'), 'weekly_digests', ['sent_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_weekly_digests_sent_at'), table_name='weekly_digests')
    op.drop_table('weekly_digests')
