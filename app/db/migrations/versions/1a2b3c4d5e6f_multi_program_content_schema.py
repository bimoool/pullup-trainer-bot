"""multi program content schema

Revision ID: 1a2b3c4d5e6f
Revises: e7c2a4f9d1b3
Create Date: 2026-09-18 05:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '1a2b3c4d5e6f'
down_revision: str | None = 'e7c2a4f9d1b3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Волна 1 многокурсовой платформы (issue #160, ветка feature/multi-program)
# — аддитивная схема каталога контента (Exercise/Complex/Program/
# AssessmentProtocol и т.п.), никак не связанная с существующей
# pull-up-специфичной схемой (кроме FK на users.id в assessment_results) и
# нигде не подключённая в проде. Порядок таблиц — по зависимостям FK:
# media_assets -> exercises -> complexes -> complex_items ->
# progression_strategy_profiles -> assessment_protocols ->
# assessment_results -> programs -> program_items.
#
# Enum-типы с префиксом mp_ (multi-program) — намеренно отдельное
# пространство имён от существующих enum'ов (equipment_type,
# workout_status и т.п.), чтобы не столкнуться по имени в общей схеме
# Postgres. mp_metric_type и mp_week_phase создаются здесь и переиспользуются
# (create_type=False) в парной миграции плана/прогресса
# (multi_program_plan_schema) — тот же приём, что уже применяется в
# 391830b06fff_elective_workouts.py для equipment_type.


def upgrade() -> None:
    op.create_table(
        'media_assets',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'exercises',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column(
            'metric_type',
            sa.Enum('reps', 'time', 'weight', 'angle', 'distance', name='mp_metric_type'),
            nullable=False,
        ),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('subcategory', sa.String(length=100), nullable=True),
        sa.Column(
            'variants', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False,
        ),
        sa.Column('media_asset_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['media_asset_id'], ['media_assets.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'complexes',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'complex_items',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('complex_id', sa.BigInteger(), nullable=False),
        sa.Column('exercise_id', sa.BigInteger(), nullable=False),
        sa.Column('order_index', sa.SmallInteger(), nullable=False),
        sa.Column('sets', sa.SmallInteger(), nullable=False),
        sa.Column('target_value', sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column('target_unit', sa.String(length=20), nullable=True),
        sa.Column('rest_seconds', sa.SmallInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['complex_id'], ['complexes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_complex_items_complex_id'), 'complex_items', ['complex_id'], unique=False)
    op.create_index(op.f('ix_complex_items_exercise_id'), 'complex_items', ['exercise_id'], unique=False)

    op.create_table(
        'progression_strategy_profiles',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'strategy_type', sa.Enum('step', 'percentage', name='mp_progression_strategy_type'), nullable=False,
        ),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'assessment_protocols',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column(
            'metric_type',
            postgresql.ENUM(
                'reps', 'time', 'weight', 'angle', 'distance', name='mp_metric_type', create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('subcategory', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'assessment_results',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('protocol_id', sa.BigInteger(), nullable=False),
        sa.Column('performed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('value', sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['protocol_id'], ['assessment_protocols.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assessment_results_protocol_id'), 'assessment_results', ['protocol_id'], unique=False)
    op.create_index(op.f('ix_assessment_results_user_id'), 'assessment_results', ['user_id'], unique=False)

    op.create_table(
        'programs',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('goal', sa.String(length=255), nullable=False),
        sa.Column(
            'structure_type',
            sa.Enum('recurring', 'fixed', 'single_lesson', name='mp_program_structure_type'),
            nullable=False,
        ),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('subcategory', sa.String(length=100), nullable=True),
        sa.Column('progression_strategy_id', sa.BigInteger(), nullable=True),
        sa.Column('reference_assessment_protocol_id', sa.BigInteger(), nullable=True),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['progression_strategy_id'], ['progression_strategy_profiles.id'], ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['reference_assessment_protocol_id'], ['assessment_protocols.id'], ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'program_items',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('program_id', sa.BigInteger(), nullable=False),
        sa.Column('week_phase', sa.Enum('base', 'rest', 'peak', name='mp_week_phase'), nullable=False),
        sa.Column('exercise_id', sa.BigInteger(), nullable=True),
        sa.Column('complex_id', sa.BigInteger(), nullable=True),
        sa.Column('count_per_week', sa.SmallInteger(), nullable=False),
        sa.Column('day_of_week', sa.SmallInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['complex_id'], ['complexes.id']),
        sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id']),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_program_items_program_id'), 'program_items', ['program_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_program_items_program_id'), table_name='program_items')
    op.drop_table('program_items')
    op.drop_table('programs')
    op.drop_index(op.f('ix_assessment_results_user_id'), table_name='assessment_results')
    op.drop_index(op.f('ix_assessment_results_protocol_id'), table_name='assessment_results')
    op.drop_table('assessment_results')
    op.drop_table('assessment_protocols')
    op.drop_table('progression_strategy_profiles')
    op.drop_index(op.f('ix_complex_items_exercise_id'), table_name='complex_items')
    op.drop_index(op.f('ix_complex_items_complex_id'), table_name='complex_items')
    op.drop_table('complex_items')
    op.drop_table('complexes')
    op.drop_table('exercises')
    op.drop_table('media_assets')

    # mp_metric_type/mp_week_phase — общие с multi_program_plan_schema, но при
    # откате она идёт ПЕРВОЙ (более новая миграция откатывается раньше) и уже
    # дропнула свои таблицы, ссылавшиеся на эти типы (plan_items и т.д.) —
    # значит к этому моменту program_items выше уже единственная оставшаяся
    # ссылка, можно безопасно дропать здесь вместе с остальными.
    for enum_name in ('mp_program_structure_type', 'mp_progression_strategy_type', 'mp_week_phase', 'mp_metric_type'):
        op.execute(f'DROP TYPE IF EXISTS {enum_name}')
