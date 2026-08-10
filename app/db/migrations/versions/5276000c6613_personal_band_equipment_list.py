"""personal band equipment list

Revision ID: 5276000c6613
Revises: 34d73f5e17a4
Create Date: 2026-08-10 19:28:21.623057

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '5276000c6613'
down_revision: str | None = '34d73f5e17a4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ВАЖНО: automatic autogenerate также предлагал снести *_archive_v1
# таблицы (созданы предыдущей миграцией 34d73f5e17a4, ORM-моделей для
# них нет — autogenerate закономерно считает их "лишними"). Это НЕ
# относится к этой миграции — они хранят реальные дореспековские данные
# пользователей, снесены здесь быть не должны. Убрано вручную из
# сгенерированного черновика, см. историю коммита.


def upgrade() -> None:
    op.create_table(
        'equipment_items',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('resistance_kg', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'position', deferrable=True, initially='DEFERRED', name='uq_equipment_items_user_position',
        ),
    )
    op.create_index(op.f('ix_equipment_items_user_id'), 'equipment_items', ['user_id'], unique=False)

    op.add_column('blocks', sa.Column('equipment_item_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_blocks_equipment_item_id'), 'blocks', ['equipment_item_id'], unique=False)
    op.create_foreign_key(
        'fk_blocks_equipment_item_id', 'blocks', 'equipment_items', ['equipment_item_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_blocks_equipment_item_id', 'blocks', type_='foreignkey')
    op.drop_index(op.f('ix_blocks_equipment_item_id'), table_name='blocks')
    op.drop_column('blocks', 'equipment_item_id')

    op.drop_index(op.f('ix_equipment_items_user_id'), table_name='equipment_items')
    op.drop_table('equipment_items')
