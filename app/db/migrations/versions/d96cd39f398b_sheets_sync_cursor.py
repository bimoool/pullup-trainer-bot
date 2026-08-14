"""sheets sync cursor

Revision ID: d96cd39f398b
Revises: b6cdb69d08cc
Create Date: 2026-08-13 23:15:43.062070

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd96cd39f398b'
down_revision: str | None = 'b6cdb69d08cc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ВАЖНО: autogenerate также предложил снести все *_archive_v1/*_archive_
# admin_reset таблицы и индекс ix_blocks_equipment_item_id (та же
# спурная разница, что повторяется в каждой миграции, см. историю) —
# убрано вручную, не связано с этой миграцией.


def upgrade() -> None:
    op.create_table(
        'sheets_sync_state',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('last_event_id', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('sheets_sync_state')
