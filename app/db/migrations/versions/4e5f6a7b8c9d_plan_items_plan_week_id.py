"""plan_items.plan_week_id

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
Create Date: 2026-09-19 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '4e5f6a7b8c9d'
down_revision: str | None = '3d4e5f6a7b8c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Checkpoint 1 многокурсовой платформы (issue #188, read-only-аудит раунда
# "PlanWeek" в переписке): plan_items -> plan_weeks не имел FK ни в одной
# миграции волны 1 (issue #160) — plan_weeks существовала как таблица без
# единой ссылающейся строки. NULL обязателен на этапе миграции схемы: у
# существующих plan_items (backfill сегодняшнего дня, реальные пользователи)
# ещё нет plan_week_id, его проставляет отдельный бэкфилл-шаг тем же
# сервисом ensure_current_plan_week, что и новый путь (app/services/
# plan_week.py) — не эта миграция и не отдельная SQL-математика.


def upgrade() -> None:
    op.add_column('plan_items', sa.Column('plan_week_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_plan_items_plan_week_id', 'plan_items', 'plan_weeks', ['plan_week_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index(op.f('ix_plan_items_plan_week_id'), 'plan_items', ['plan_week_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_plan_items_plan_week_id'), table_name='plan_items')
    op.drop_constraint('fk_plan_items_plan_week_id', 'plan_items', type_='foreignkey')
    op.drop_column('plan_items', 'plan_week_id')
