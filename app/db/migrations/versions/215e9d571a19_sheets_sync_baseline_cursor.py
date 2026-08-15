"""sheets sync baseline cursor

Revision ID: 215e9d571a19
Revises: 4c738120a6fe
Create Date: 2026-08-15 22:33:21.017980

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '215e9d571a19'
down_revision: str | None = '4c738120a6fe'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ВАЖНО: autogenerate также предложил снести все *_archive_v1/*_archive_
# admin_reset таблицы и индекс ix_blocks_equipment_item_id (та же спурная
# разница, что повторяется в каждой миграции, см. историю) — убрано
# вручную, не связано с этой миграцией.


def upgrade() -> None:
    op.add_column('sheets_sync_state', sa.Column('last_baseline_id', sa.BigInteger(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('sheets_sync_state', 'last_baseline_id')
