"""multi program plan schema

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-09-18 05:21:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '2b3c4d5e6f7a'
down_revision: str | None = '1a2b3c4d5e6f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Волна 1 многокурсовой платформы (issue #160), вторая половина — план и
# прогресс пользователя (TrainingPlan/PlanWeek/ProgramInclusion/PlanItem/
# TrainingSession/SessionBlock/SetTarget/SetLog), поверх контентной схемы
# multi_program_content_schema. Порядок — по зависимостям FK: training_plans
# -> plan_weeks -> program_inclusions -> plan_items -> training_sessions ->
# session_plan_items -> session_blocks -> set_targets -> set_logs.
#
# TrainingSession/SessionBlock — переименованы относительно терминов
# документа turnikmen-multicourse-architecture.md (раздел 2): Session ->
# TrainingSession (коллизия с sqlalchemy.orm.Session), Block -> SessionBlock
# (коллизия с уже существующим app.db.models.Block — блок А/Б подтягиваний).
#
# TrainingSession.source включает elective четвёртым значением (поправка
# Кирилла в issue #160) — миграция данных из app.db.models.ElectiveWorkout
# в TrainingSession НЕ делается здесь, это задел волны 2.


def upgrade() -> None:
    op.create_table(
        'training_plans',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_training_plans_user_id'), 'training_plans', ['user_id'], unique=True)

    op.create_table(
        'plan_weeks',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('training_plan_id', sa.BigInteger(), nullable=False),
        sa.Column('week_number', sa.SmallInteger(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column(
            'phase',
            postgresql.ENUM('base', 'rest', 'peak', name='mp_week_phase', create_type=False),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['training_plan_id'], ['training_plans.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('training_plan_id', 'week_number', name='uq_plan_weeks_plan_week_number'),
    )
    op.create_index(op.f('ix_plan_weeks_training_plan_id'), 'plan_weeks', ['training_plan_id'], unique=False)

    op.create_table(
        'program_inclusions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('training_plan_id', sa.BigInteger(), nullable=False),
        sa.Column('program_id', sa.BigInteger(), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('progression_state', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id']),
        sa.ForeignKeyConstraint(['training_plan_id'], ['training_plans.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_program_inclusions_training_plan_id'), 'program_inclusions', ['training_plan_id'], unique=False,
    )
    op.create_index(op.f('ix_program_inclusions_program_id'), 'program_inclusions', ['program_id'], unique=False)

    op.create_table(
        'plan_items',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('training_plan_id', sa.BigInteger(), nullable=False),
        sa.Column('exercise_id', sa.BigInteger(), nullable=False),
        sa.Column('complex_id', sa.BigInteger(), nullable=True),
        sa.Column('count_per_week', sa.SmallInteger(), nullable=False),
        sa.Column('day_of_week', sa.SmallInteger(), nullable=True),
        sa.Column(
            'week_phase',
            postgresql.ENUM('base', 'rest', 'peak', name='mp_week_phase', create_type=False),
            nullable=True,
        ),
        sa.Column('program_inclusion_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['complex_id'], ['complexes.id']),
        sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id']),
        sa.ForeignKeyConstraint(['program_inclusion_id'], ['program_inclusions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['training_plan_id'], ['training_plans.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_plan_items_training_plan_id'), 'plan_items', ['training_plan_id'], unique=False)
    op.create_index(op.f('ix_plan_items_exercise_id'), 'plan_items', ['exercise_id'], unique=False)

    op.create_table(
        'training_sessions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'source',
            sa.Enum('plan', 'freeform', 'backdated', 'elective', name='mp_session_source'),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.Enum('started', 'completed', name='mp_session_status'),
            server_default='started',
            nullable=False,
        ),
        sa.Column('performed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('effort', sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_training_sessions_user_id'), 'training_sessions', ['user_id'], unique=False)

    op.create_table(
        'session_plan_items',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('session_id', sa.BigInteger(), nullable=False),
        sa.Column('plan_item_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['plan_item_id'], ['plan_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['training_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'plan_item_id', name='uq_session_plan_items_session_plan_item'),
    )
    op.create_index(op.f('ix_session_plan_items_session_id'), 'session_plan_items', ['session_id'], unique=False)
    op.create_index(
        op.f('ix_session_plan_items_plan_item_id'), 'session_plan_items', ['plan_item_id'], unique=False,
    )

    op.create_table(
        'session_blocks',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('session_id', sa.BigInteger(), nullable=False),
        sa.Column('order_index', sa.SmallInteger(), nullable=False),
        sa.Column('exercise_id', sa.BigInteger(), nullable=True),
        sa.Column('complex_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['complex_id'], ['complexes.id']),
        sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id']),
        sa.ForeignKeyConstraint(['session_id'], ['training_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_session_blocks_session_id'), 'session_blocks', ['session_id'], unique=False)

    op.create_table(
        'set_targets',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('session_block_id', sa.BigInteger(), nullable=False),
        sa.Column('set_number', sa.SmallInteger(), nullable=False),
        sa.Column('is_max_set', sa.Boolean(), server_default='false', nullable=False),
        sa.Column(
            'metric_type',
            postgresql.ENUM(
                'reps', 'time', 'weight', 'angle', 'distance', name='mp_metric_type', create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('value', sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('effort', sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_block_id'], ['session_blocks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_set_targets_session_block_id'), 'set_targets', ['session_block_id'], unique=False)

    op.create_table(
        'set_logs',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('session_block_id', sa.BigInteger(), nullable=False),
        sa.Column('set_target_id', sa.BigInteger(), nullable=True),
        sa.Column('set_number', sa.SmallInteger(), nullable=False),
        sa.Column('is_max_set', sa.Boolean(), server_default='false', nullable=False),
        sa.Column(
            'metric_type',
            postgresql.ENUM(
                'reps', 'time', 'weight', 'angle', 'distance', name='mp_metric_type', create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('value', sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('effort', sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_block_id'], ['session_blocks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['set_target_id'], ['set_targets.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_set_logs_session_block_id'), 'set_logs', ['session_block_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_set_logs_session_block_id'), table_name='set_logs')
    op.drop_table('set_logs')
    op.drop_index(op.f('ix_set_targets_session_block_id'), table_name='set_targets')
    op.drop_table('set_targets')
    op.drop_index(op.f('ix_session_blocks_session_id'), table_name='session_blocks')
    op.drop_table('session_blocks')
    op.drop_index(op.f('ix_session_plan_items_plan_item_id'), table_name='session_plan_items')
    op.drop_index(op.f('ix_session_plan_items_session_id'), table_name='session_plan_items')
    op.drop_table('session_plan_items')
    op.drop_index(op.f('ix_training_sessions_user_id'), table_name='training_sessions')
    op.drop_table('training_sessions')
    op.drop_index(op.f('ix_plan_items_exercise_id'), table_name='plan_items')
    op.drop_index(op.f('ix_plan_items_training_plan_id'), table_name='plan_items')
    op.drop_table('plan_items')
    op.drop_index(op.f('ix_program_inclusions_program_id'), table_name='program_inclusions')
    op.drop_index(op.f('ix_program_inclusions_training_plan_id'), table_name='program_inclusions')
    op.drop_table('program_inclusions')
    op.drop_index(op.f('ix_plan_weeks_training_plan_id'), table_name='plan_weeks')
    op.drop_table('plan_weeks')
    op.drop_index(op.f('ix_training_plans_user_id'), table_name='training_plans')
    op.drop_table('training_plans')

    # mp_session_status/mp_session_source используются только здесь — дропаются
    # сразу. mp_week_phase/mp_metric_type общие с multi_program_content_schema
    # (program_items.week_phase там всё ещё жив на этот момент отката —
    # downgrade идёт от новой миграции к старой, значит content_schema
    # откатывается ВТОРЫМ шагом и должна дропать эти два типа сама, после
    # своей собственной program_items).
    for enum_name in ('mp_session_status', 'mp_session_source'):
        op.execute(f'DROP TYPE IF EXISTS {enum_name}')
