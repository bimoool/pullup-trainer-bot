"""work sets growth reason (stall/ceiling explanation, issue #79)

Revision ID: c9e3a1f7b4d6
Revises: a7c1e4f8b3d2
Create Date: 2026-09-09 04:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c9e3a1f7b4d6'
down_revision: str | None = 'a7c1e4f8b3d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Почему выросли work_sets ЭТОЙ тренировки блока A — "stall"/"ceiling"
    # (app.domain.constants.VolumeGrowthReason) или NULL, если не выросли
    # (в т.ч. блок B — там подходы фиксированы). String(10), не Postgres
    # enum — всего два значения, ALTER TYPE ради такого расширения не нужен.
    op.add_column('blocks', sa.Column('work_sets_growth_reason', sa.String(length=10), nullable=True))

    # blocks_archive_admin_reset — тот же снимок структуры (CREATE TABLE ...
    # (LIKE blocks)), что уже один раз ловил рассинхрон при похожей правке
    # (e2c7a4f19d3b, см. docs/deploy.md) — добавляем колонку синхронно, иначе
    # "🧪 Полный сброс" сломается на первом же вызове после этой ревизии.
    op.add_column(
        'blocks_archive_admin_reset', sa.Column('work_sets_growth_reason', sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('blocks_archive_admin_reset', 'work_sets_growth_reason')
    op.drop_column('blocks', 'work_sets_growth_reason')
