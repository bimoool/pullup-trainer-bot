"""volume block growth state (work_sets, deload)

Revision ID: e2c7a4f19d3b
Revises: 8a1f4c6e9b2d
Create Date: 2026-08-25 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e2c7a4f19d3b'
down_revision: str | None = '8a1f4c6e9b2d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ревизия формулы прогрессии — блок на объём получает переменное число
    # рабочих подходов (растёт по правилу застоя/потолка, см.
    # app.domain.progression.recalculate_volume_block) вместо фиксированной
    # константы. work_sets_before/after — NULL для блока B и для всех уже
    # существующих исторических записей блока A (их структурное число
    # подходов на момент записи было VOLUME_BLOCK.work_sets=3 — не
    # бэкфиллим прошлое явным значением, читающий код (_resolve_next_state)
    # трактует NULL как "3, стартовое").
    op.add_column('blocks', sa.Column('work_sets_before', sa.SmallInteger(), nullable=True))
    op.add_column('blocks', sa.Column('work_sets_after', sa.SmallInteger(), nullable=True))
    op.add_column(
        'blocks',
        sa.Column('is_deload', sa.Boolean(), nullable=False, server_default='false'),
    )

    # blocks_archive_admin_reset — постоянная архивная таблица под "🧪 Полный
    # сброс" (b41882a0e3e8), созданная через CREATE TABLE ... (LIKE blocks) —
    # это СНИМОК структуры на момент создания, не следит за ALTER TABLE на
    # blocks сама по себе. admin_reset.py делает "INSERT ... SELECT b.* FROM
    # blocks", так что без этих же трёх колонок здесь INSERT сломался бы
    # ("has more expressions than target columns") при первом же вызове
    # после этой ревизии — добавляем синхронно.
    op.add_column('blocks_archive_admin_reset', sa.Column('work_sets_before', sa.SmallInteger(), nullable=True))
    op.add_column('blocks_archive_admin_reset', sa.Column('work_sets_after', sa.SmallInteger(), nullable=True))
    op.add_column(
        'blocks_archive_admin_reset',
        sa.Column('is_deload', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('blocks_archive_admin_reset', 'is_deload')
    op.drop_column('blocks_archive_admin_reset', 'work_sets_after')
    op.drop_column('blocks_archive_admin_reset', 'work_sets_before')

    op.drop_column('blocks', 'is_deload')
    op.drop_column('blocks', 'work_sets_after')
    op.drop_column('blocks', 'work_sets_before')
