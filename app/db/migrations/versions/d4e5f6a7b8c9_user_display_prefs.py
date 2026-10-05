"""user display prefs (units, theme)

Revision ID: 7c1d9e2f4a68
Revises: b8c9d0e1f2a3
Create Date: 2026-10-02 06:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '7c1d9e2f4a68'
down_revision: str | None = 'b8c9d0e1f2a3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Настройки отображения Mini App (issue #268): единицы веса/роста и тема.
# NULL = "не настраивал", дефолты (kg/cm/auto) резолвятся на чтении. Хранение
# остаётся метрическим (weight_kg/height_cm) — единицы только для показа/ввода.
# Аддитивно: старый код колонки не читает.


def upgrade() -> None:
    op.add_column('users', sa.Column('weight_unit', sa.String(), nullable=True))
    op.add_column('users', sa.Column('height_unit', sa.String(), nullable=True))
    op.add_column('users', sa.Column('theme_pref', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'theme_pref')
    op.drop_column('users', 'height_unit')
    op.drop_column('users', 'weight_unit')
