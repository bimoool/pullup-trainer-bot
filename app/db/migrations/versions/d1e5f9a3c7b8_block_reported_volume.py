"""block reported_volume (freeform total without per-set breakdown, issue #88)

Revision ID: d1e5f9a3c7b8
Revises: c9e3a1f7b4d6
Create Date: 2026-09-11 17:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd1e5f9a3c7b8'
down_revision: str | None = 'c9e3a1f7b4d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Итог за тренировку без раскладки по подходам (бэкдейт блока Б, "не
    # помню по подходам, но итог знаю") — NULL для обычных записей, см.
    # app.db.models.Block.reported_volume / app.domain.session.BlockLog.
    op.add_column('blocks', sa.Column('reported_volume', sa.SmallInteger(), nullable=True))

    # blocks_archive_admin_reset — тот же снимок структуры (CREATE TABLE ...
    # (LIKE blocks)), что уже один раз ловил рассинхрон при похожей правке
    # (e2c7a4f19d3b, см. CLAUDE.md) — добавляем колонку синхронно, иначе
    # "🧪 Полный сброс" сломается на первом же вызове после этой ревизии.
    op.add_column('blocks_archive_admin_reset', sa.Column('reported_volume', sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('blocks_archive_admin_reset', 'reported_volume')
    op.drop_column('blocks', 'reported_volume')
