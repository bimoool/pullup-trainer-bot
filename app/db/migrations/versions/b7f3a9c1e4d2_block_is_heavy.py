"""block is_heavy (alternating heavy strength training, issue #97)

Revision ID: b7f3a9c1e4d2
Revises: af5a2d961a52
Create Date: 2026-09-12 17:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b7f3a9c1e4d2'
down_revision: str | None = 'af5a2d961a52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Чётная ("тяжёлая") тренировка блока Б (issue #97) — только для
    # block_type=B, см. app.db.models.Block.is_heavy.
    op.add_column('blocks', sa.Column('is_heavy', sa.Boolean(), nullable=False, server_default='false'))

    # blocks_archive_admin_reset — тот же снимок структуры (CREATE TABLE ...
    # (LIKE blocks)), что уже один раз ловил рассинхрон при похожей правке
    # (e2c7a4f19d3b, см. CLAUDE.md) — добавляем колонку синхронно, иначе
    # "🧪 Полный сброс" сломается на первом же вызове после этой ревизии.
    op.add_column(
        'blocks_archive_admin_reset', sa.Column('is_heavy', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('blocks_archive_admin_reset', 'is_heavy')
    op.drop_column('blocks', 'is_heavy')
