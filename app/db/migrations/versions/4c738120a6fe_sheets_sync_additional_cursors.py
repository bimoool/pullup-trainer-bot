"""sheets sync additional cursors

Revision ID: 4c738120a6fe
Revises: 391830b06fff
Create Date: 2026-08-14 11:40:42.000380

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '4c738120a6fe'
down_revision: str | None = '391830b06fff'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ВАЖНО: autogenerate также предложил снести все *_archive_v1/*_archive_
# admin_reset таблицы и индекс ix_blocks_equipment_item_id (та же спурная
# разница, что повторяется в каждой миграции, см. историю) — убрано
# вручную, не связано с этой миграцией.


def upgrade() -> None:
    op.add_column('sheets_sync_state', sa.Column('last_workout_id', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('sheets_sync_state', sa.Column('last_elective_id', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column(
        'sheets_sync_state', sa.Column('last_subscription_id', sa.BigInteger(), server_default='0', nullable=False),
    )
    op.add_column('sheets_sync_state', sa.Column('last_coin_id', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column(
        'sheets_sync_state', sa.Column('last_achievement_id', sa.BigInteger(), server_default='0', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('sheets_sync_state', 'last_achievement_id')
    op.drop_column('sheets_sync_state', 'last_coin_id')
    op.drop_column('sheets_sync_state', 'last_subscription_id')
    op.drop_column('sheets_sync_state', 'last_elective_id')
    op.drop_column('sheets_sync_state', 'last_workout_id')
