"""workout drafts

Revision ID: f1a2b3c4d5e6
Revises: d3f8b2a71c5e
Create Date: 2026-09-05 07:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f1a2b3c4d5e6'
down_revision: str | None = 'd3f8b2a71c5e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Черновик тренировки в реальном времени (issue #61) — накопленные
# результаты уже завершённых подходов, переживает закрытие Telegram
# посреди тренировки. Не трогает *_archive_admin_reset таблицы (тот список
# ограничен workouts/blocks/workout_sets/baselines/equipment_items, см.
# docs/deploy.md) — черновик к прогрессии/истории тренировок не относится,
# как и active_timers.


def upgrade() -> None:
    op.create_table(
        'workout_drafts',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('block_a_working_reps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('block_a_max_reps', sa.SmallInteger(), nullable=True),
        sa.Column('block_b_working_reps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('block_b_max_reps', sa.SmallInteger(), nullable=True),
        sa.Column('block_a_actual_weight', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('block_b_actual_weight', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('block_a_actual_band_item_id', sa.BigInteger(), nullable=True),
        sa.Column('block_b_actual_band_item_id', sa.BigInteger(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workout_drafts_user_id'), 'workout_drafts', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_workout_drafts_user_id'), table_name='workout_drafts')
    op.drop_table('workout_drafts')
