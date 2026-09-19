"""timer sound volume

Revision ID: a9d4e6f2b8c1
Revises: c9e3a1f7b4d6
Create Date: 2026-09-11 16:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a9d4e6f2b8c1'
down_revision: str | None = 'c9e3a1f7b4d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Громкость звука таймера Mini App, 0..100% (issue #90) — тот же принцип, что
# у d3f8b2a71c5e (rest_seconds_block_a/b/big_break_seconds): NULL = "не
# настраивал, использовать дефолт" (см.
# app.domain.constants.DEFAULT_TIMER_SOUND_VOLUME_PERCENT), без server_default
# — NULL здесь постоянное валидное состояние, не временное. users не входит в
# список *_archive_admin_reset таблиц (workouts/blocks/workout_sets/
# baselines/equipment_items, см. docs/deploy.md) — архивные таблицы не тронуты.


def upgrade() -> None:
    op.add_column('users', sa.Column('sound_volume_percent', sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'sound_volume_percent')
