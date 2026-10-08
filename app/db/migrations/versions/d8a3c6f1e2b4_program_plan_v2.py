"""Program + Plan v2: occurrences, explicit session credit, constraints, custom plans (issue #304)

Revision ID: d8a3c6f1e2b4
Revises: b7d2e9f4a1c3
Create Date: 2026-10-08 18:00:00.000000

"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd8a3c6f1e2b4'
down_revision: str | None = 'b7d2e9f4a1c3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DOMAIN-V2 Wave 1b (docs/domain/PROGRAM_PLAN_V2.md §1, §2, §4–§7; MIGRATION_V2.md §1, §3, §5).
#
# Expand — только аддитивно, старый код продолжает работать (INSERT старого кода новых колонок не
# знает: всё NULLABLE или с server_default):
#   * programs: slots, frequency, constraints, assessment (JSONB, NULL);
#   * program_inclusions: progression_state_rev, sequence_cursor, baseline_assessment_result_id,
#     status, completed_main_sessions, last_main_session_at;
#   * новая таблица custom_plans (свой план: ротация тренировок + объём по неделям, 0 допустим);
#   * plan_items: source, workout_definition_id, occurrence_index, origin_plan_week_id,
#     scheduled_date, program_slot_key, custom_plan_id, status, legacy_aggregate;
#   * training_sessions.plan_item_id — явный кредит не более ОДНОГО занятия (PL2).
# Ни одна колонка не переименована, не сменила тип и не удалена. session_plan_items (M2M) остаётся
# как есть — только для чтения истории; новые записи кредита идут через plan_item_id.
#
# Backfill — детерминированный, литеральный SQL (ничего из app.* не импортируется: правка рантайма
# не меняет того, что пишет эта ревизия), повторный прогон = 0 изменений (всё «WHERE ... IS NULL»):
#   1. каталог «Подтягивания» (system, category pull_ups, STEP): slots/frequency/constraints/
#      assessment — OD-2: main = ДВА ПОЛНЫХ дня отдыха → min_days_between_starts = 3 (Пн → Чт);
#      config.min_rest_days (старая семантика «Пн → Ср») НЕ трогается и не читается;
#   2. program_inclusions.status = active | removed по is_active (inclusion без status — старый код);
#   3. plan_items.source = program | manual, workout_definition_id = complex_id;
#   4. training_sessions.plan_item_id = единственная связанная M2M-строка, если ровно одна
#      (MIGRATION_V2 §3; пары A+B курса разворачивает converge_user_plan, не эта ревизия).
# Разворот агрегатных строк текущей/будущих недель в занятия — НЕ здесь, а в единственной
# идемпотентной app.services.plan_convergence.converge_user_plan (MIGRATION_V2 §5): ей нужны
# «сегодня» и часовой пояс пользователя. Подписки (users.subscription_*, subscriptions) и
# programs.access_level не читаются и не пишутся (MIGRATION_V2 §7).
#
# downgrade: снимает только добавленное этой ревизией. Потеря при откате схемы: явный кредит
# (plan_item_id), строки своих планов, разметка занятий и статусы включений. Занятия, созданные
# converge_user_plan, остаются строками plan_items (count_per_week = 1) — старый код читает их как
# обычные строки недели; выведенные из плана агрегаты (status = removed) старому коду снова видны рядом
# с ними (колонки status больше нет). M2M-связи истории и сами сессии не тронуты. Повторный upgrade
# восстанавливает backfill 1–4, разворот — следующий converge_user_plan.

_PULLUPS_PROGRAM_NAME = 'Подтягивания'
_PULLUPS_PROGRAM_CATEGORY = 'pull_ups'
_ASSESSMENT_PROTOCOL_NAME = 'Максимум подтягиваний'
_MAIN_SLOTS = [{
    'key': 'main', 'role': 'main', 'workout_definition_id': None, 'spacing_group': 'main',
    'repeat': 'every_session', 'counts_toward_progression': True,
}]
_MAIN_FREQUENCY = {'sessions_per_week': 3, 'per_slot': {}}
_MAIN_CONSTRAINTS = [{'spacing_group': 'main', 'min_days_between_starts': 3}]
_ASSESSMENT_VALIDITY_DAYS = 35  # BASELINE_VALID_DAYS на 2026-10-08 (литерал, не импорт)


def upgrade() -> None:
    for column in ('slots', 'frequency', 'constraints', 'assessment'):
        op.add_column('programs', sa.Column(column, postgresql.JSONB(), nullable=True))

    op.add_column(
        'program_inclusions',
        sa.Column('progression_state_rev', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column('program_inclusions', sa.Column('sequence_cursor', sa.Integer(), nullable=True))
    op.add_column(
        'program_inclusions',
        sa.Column(
            'baseline_assessment_result_id', sa.BigInteger(),
            sa.ForeignKey('assessment_results.id', ondelete='SET NULL'), nullable=True,
        ),
    )
    op.add_column('program_inclusions', sa.Column('status', sa.String(length=16), nullable=True))
    op.add_column('program_inclusions', sa.Column('completed_main_sessions', sa.Integer(), nullable=True))
    op.add_column(
        'program_inclusions', sa.Column('last_main_session_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'custom_plans',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column(
            'user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True,
        ),
        sa.Column(
            'training_plan_id', sa.BigInteger(), sa.ForeignKey('training_plans.id', ondelete='CASCADE'),
            nullable=False, index=True,
        ),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('start_week_number', sa.SmallInteger(), nullable=False),
        sa.Column('workouts', postgresql.JSONB(), nullable=False),
        sa.Column('weeks', postgresql.JSONB(), nullable=False),
        sa.Column('repeat', sa.String(length=16), nullable=False, server_default='once'),
        sa.Column('preferred_weekdays', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.add_column('plan_items', sa.Column('source', sa.String(length=16), nullable=True))
    op.add_column(
        'plan_items',
        sa.Column('workout_definition_id', sa.BigInteger(), sa.ForeignKey('complexes.id'), nullable=True),
    )
    op.add_column('plan_items', sa.Column('occurrence_index', sa.SmallInteger(), nullable=True))
    op.add_column(
        'plan_items',
        sa.Column(
            'origin_plan_week_id', sa.BigInteger(), sa.ForeignKey('plan_weeks.id', ondelete='CASCADE'),
            nullable=True,
        ),
    )
    op.add_column('plan_items', sa.Column('scheduled_date', sa.Date(), nullable=True))
    op.add_column('plan_items', sa.Column('program_slot_key', sa.String(length=32), nullable=True))
    op.add_column(
        'plan_items',
        sa.Column(
            'custom_plan_id', sa.BigInteger(), sa.ForeignKey('custom_plans.id', ondelete='SET NULL'), nullable=True,
        ),
    )
    op.add_column('plan_items', sa.Column('status', sa.String(length=16), nullable=False, server_default='open'))
    op.add_column(
        'plan_items', sa.Column('legacy_aggregate', sa.Boolean(), nullable=False, server_default='false'),
    )
    # Идемпотентность генерации занятий: одно занятие (источник, слот, номер) на неделю-источник.
    op.create_index(
        'uq_plan_items_program_occurrence', 'plan_items',
        ['origin_plan_week_id', 'program_inclusion_id', 'program_slot_key', 'occurrence_index'],
        unique=True,
        postgresql_where=sa.text('program_inclusion_id IS NOT NULL AND occurrence_index IS NOT NULL'),
    )
    op.create_index(
        'uq_plan_items_custom_occurrence', 'plan_items',
        ['origin_plan_week_id', 'custom_plan_id', 'occurrence_index'],
        unique=True,
        postgresql_where=sa.text('custom_plan_id IS NOT NULL AND occurrence_index IS NOT NULL'),
    )

    op.add_column(
        'training_sessions',
        sa.Column(
            'plan_item_id', sa.BigInteger(), sa.ForeignKey('plan_items.id', ondelete='SET NULL'), nullable=True,
        ),
    )
    op.create_index('ix_training_sessions_plan_item_id', 'training_sessions', ['plan_item_id'])

    _backfill()


def _backfill() -> None:
    conn = op.get_bind()
    protocol_id = conn.execute(
        sa.text('SELECT id FROM assessment_protocols WHERE name = :name ORDER BY id LIMIT 1'),
        {'name': _ASSESSMENT_PROTOCOL_NAME},
    ).scalar()
    assessment = {
        'protocol_id': protocol_id, 'required_before_first_session': True,
        'validity_days': _ASSESSMENT_VALIDITY_DAYS,
    }
    conn.execute(
        sa.text(
            "UPDATE programs p SET "
            "slots = COALESCE(p.slots, CAST(:slots AS jsonb)), "
            "frequency = COALESCE(p.frequency, CAST(:frequency AS jsonb)), "
            "constraints = COALESCE(p.constraints, CAST(:constraints AS jsonb)), "
            "assessment = COALESCE(p.assessment, CAST(:assessment AS jsonb)) "
            "WHERE p.name = :name AND p.category = :category "
            "AND (p.slots IS NULL OR p.frequency IS NULL OR p.constraints IS NULL OR p.assessment IS NULL) "
            "AND EXISTS (SELECT 1 FROM progression_strategy_profiles s "
            "            WHERE s.id = p.progression_strategy_id AND s.strategy_type = 'step')"
        ),
        {
            'slots': json.dumps(_MAIN_SLOTS), 'frequency': json.dumps(_MAIN_FREQUENCY),
            'constraints': json.dumps(_MAIN_CONSTRAINTS), 'assessment': json.dumps(assessment),
            'name': _PULLUPS_PROGRAM_NAME, 'category': _PULLUPS_PROGRAM_CATEGORY,
        },
    )
    conn.execute(sa.text(
        "UPDATE program_inclusions SET status = CASE WHEN is_active THEN 'active' ELSE 'removed' END "
        "WHERE status IS NULL"
    ))
    conn.execute(sa.text(
        "UPDATE plan_items SET source = CASE WHEN program_inclusion_id IS NULL THEN 'manual' ELSE 'program' END "
        "WHERE source IS NULL"
    ))
    conn.execute(sa.text(
        "UPDATE plan_items SET workout_definition_id = complex_id "
        "WHERE workout_definition_id IS NULL AND complex_id IS NOT NULL"
    ))
    conn.execute(sa.text(
        "UPDATE training_sessions t SET plan_item_id = single.plan_item_id "
        "FROM (SELECT session_id, MIN(plan_item_id) AS plan_item_id FROM session_plan_items "
        "      GROUP BY session_id HAVING COUNT(*) = 1) AS single "
        "WHERE t.id = single.session_id AND t.plan_item_id IS NULL"
    ))


def downgrade() -> None:
    op.drop_index('ix_training_sessions_plan_item_id', table_name='training_sessions')
    op.drop_column('training_sessions', 'plan_item_id')
    op.drop_index('uq_plan_items_custom_occurrence', table_name='plan_items')
    op.drop_index('uq_plan_items_program_occurrence', table_name='plan_items')
    for column in (
        'legacy_aggregate', 'status', 'custom_plan_id', 'program_slot_key', 'scheduled_date',
        'origin_plan_week_id', 'occurrence_index', 'workout_definition_id', 'source',
    ):
        op.drop_column('plan_items', column)
    op.drop_table('custom_plans')
    for column in (
        'last_main_session_at', 'completed_main_sessions', 'status', 'baseline_assessment_result_id',
        'sequence_cursor', 'progression_state_rev',
    ):
        op.drop_column('program_inclusions', column)
    for column in ('assessment', 'constraints', 'frequency', 'slots'):
        op.drop_column('programs', column)
