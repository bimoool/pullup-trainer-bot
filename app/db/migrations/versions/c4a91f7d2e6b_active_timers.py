"""active timers

Revision ID: c4a91f7d2e6b
Revises: 48eccea08c8b
Create Date: 2026-09-04 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c4a91f7d2e6b'
down_revision: str | None = '48eccea08c8b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Не трогает *_archive_admin_reset таблицы (issue #59) — тот список
# ограничен workouts/blocks/workout_sets/baselines/equipment_items (см.
# CLAUDE.md), активный таймер к прогрессии/истории тренировок не относится.


def upgrade() -> None:
    op.create_table(
        'active_timers',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'timer_type',
            sa.Enum('rest_between_sets', 'big_break', name='active_timer_type'),
            nullable=False,
        ),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('block_letter', sa.String(length=1), nullable=True),
        sa.Column('set_number', sa.SmallInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_active_timers_user_id'), 'active_timers', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_active_timers_user_id'), table_name='active_timers')
    op.drop_table('active_timers')
    op.execute('DROP TYPE active_timer_type')
