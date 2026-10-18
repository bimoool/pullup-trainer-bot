"""custom_plans.spec — количество тренировок по неделям и фазы (UX-EDITOR)

Revision ID: c7e2a9d4b1f8
Revises: b5d8e1f3a6c9
Create Date: 2026-10-18

Одна nullable-колонка, без бэкфилла: NULL = план старой формы (матрица выводится на чтении из
workouts + weeks). Архивной *_archive_admin_reset-пары у custom_plans нет.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7e2a9d4b1f8"
down_revision = "b5d8e1f3a6c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("custom_plans", sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("custom_plans", "spec")
