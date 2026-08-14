"""elective workouts

Revision ID: 391830b06fff
Revises: d96cd39f398b
Create Date: 2026-08-14 11:20:35.051363

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '391830b06fff'
down_revision: str | None = 'd96cd39f398b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ВАЖНО: autogenerate также предложил снести все *_archive_v1/*_archive_
# admin_reset таблицы и индекс ix_blocks_equipment_item_id (та же спурная
# разница, что повторяется в каждой миграции, см. историю) — убрано
# вручную, не связано с этой миграцией.
#
# equipment_type — create_type=False: тип уже создан миграцией
# 34d73f5e17a4, здесь только переиспользуется на новой таблице (тот же
# паттерн, что и там для blocks/baselines).


def upgrade() -> None:
    op.create_table(
        'elective_workouts',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'elective_type',
            sa.Enum('max_reps_ladder', 'w_ladder', 'three_minutes', 'volume_target', name='elective_type'),
            nullable=False,
        ),
        sa.Column('performed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reps_sequence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('total_reps', sa.Integer(), nullable=False),
        sa.Column(
            'equipment_type',
            postgresql.ENUM('band', 'bodyweight', 'weight', 'australian', name='equipment_type', create_type=False),
            nullable=False,
        ),
        sa.Column('equipment_value', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('equipment_item_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['equipment_item_id'], ['equipment_items.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_elective_workouts_user_id'), 'elective_workouts', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_elective_workouts_user_id'), table_name='elective_workouts')
    op.drop_table('elective_workouts')
    op.execute('DROP TYPE elective_type')
