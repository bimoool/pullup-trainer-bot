"""timer preferences

Revision ID: d3f8b2a71c5e
Revises: c4a91f7d2e6b
Create Date: 2026-09-04 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd3f8b2a71c5e'
down_revision: str | None = 'c4a91f7d2e6b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Персистентные настройки длительности таймера (issue #59, волна 2) —
# NULL = "не настраивал, использовать дефолт" (см.
# app.domain.constants.DEFAULT_REST_SECONDS_BLOCK_A/B/DEFAULT_BIG_BREAK_SECONDS),
# без server_default: NULL здесь постоянное валидное состояние, не временное.
# users не входит в список *_archive_admin_reset таблиц (workouts/blocks/
# workout_sets/baselines/equipment_items, см. docs/deploy.md) — архивные
# таблицы не тронуты.


def upgrade() -> None:
    op.add_column('users', sa.Column('rest_seconds_block_a', sa.SmallInteger(), nullable=True))
    op.add_column('users', sa.Column('rest_seconds_block_b', sa.SmallInteger(), nullable=True))
    op.add_column('users', sa.Column('big_break_seconds', sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'big_break_seconds')
    op.drop_column('users', 'rest_seconds_block_b')
    op.drop_column('users', 'rest_seconds_block_a')
