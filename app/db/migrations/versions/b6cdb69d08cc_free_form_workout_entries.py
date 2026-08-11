"""free-form workout entries

Revision ID: b6cdb69d08cc
Revises: 13c6ffb16123
Create Date: 2026-08-11 23:11:28.151406

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b6cdb69d08cc'
down_revision: str | None = '13c6ffb16123'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ВАЖНО: autogenerate также предложил снести все *_archive_v1/*_archive_
# admin_reset таблицы (нет ORM-моделей — то же самое повторяется в каждой
# миграции, см. историю) и индекс ix_blocks_equipment_item_id (расхождение
# со старой миграции, не связано с этой) — убрано вручную.
#
# workouts_archive_admin_reset (см. b41882a0e3e8) — снимок структуры
# workouts НА МОМЕНТ создания (голый LIKE, без отслеживания будущих ALTER
# TABLE источника) — "🧪 Полный сброс" делает INSERT INTO ... SELECT * FROM
# workouts, поэтому при каждом добавлении колонки в workouts архивную
# таблицу нужно обновлять вручную здесь же, иначе список колонок
# разъедется и сброс сломается (ловится тестом test_admin_testing_mode.py).


def upgrade() -> None:
    op.add_column('workouts', sa.Column('is_free_entry', sa.Boolean(), server_default='false', nullable=False))
    op.add_column(
        'workouts_archive_admin_reset', sa.Column('is_free_entry', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('workouts_archive_admin_reset', 'is_free_entry')
    op.drop_column('workouts', 'is_free_entry')
