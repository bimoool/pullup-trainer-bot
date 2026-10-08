"""WorkoutDefinition v2: versions, exercise identity, re-authored system content (issue #303)

Revision ID: b7d2e9f4a1c3
Revises: c3f7a9e2d5b1
Create Date: 2026-10-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.migrations._frozen.b7d2e9f4a1c3_backfill import run_backfill

revision: str = 'b7d2e9f4a1c3'
down_revision: str | None = 'c3f7a9e2d5b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DOMAIN-V2 Wave 1a (docs/domain/WORKOUT_DOMAIN_V2.md, MIGRATION_V2.md §1, §3).
#
# Expand — только аддитивно, старый код работает как прежде:
#   * новая таблица exercise_categories (справочник с display_name);
#   * exercises: display_name, slug, category_id, subcategory_id, visibility, analytics_exercise_id —
#     все NULLABLE (INSERT старого кода их не знает); name/category/subcategory не трогаются;
#   * новая таблица workout_definition_versions (неизменяемые версии, триггер запрещает UPDATE);
#   * complexes.current_version_id — NULLABLE FK, ON DELETE SET NULL.
# complex_items.protocol (V1) не меняется и остаётся читаемым.
#
# Backfill — app/db/migrations/_frozen/b7d2e9f4a1c3_backfill.run_backfill: ЗАМОРОЖЕННЫЙ помощник этой
# ревизии (stdlib + SQLAlchemy, без app.domain.* и прочего рантайм-кода — WORKOUT_DOMAIN_V2 §9.10):
# будущая правка рантайм-семантики не меняет того, что пишет эта ревизия. Детерминированно
# (ORDER BY id), по натуральным ключам, повторный прогон = 0 изменений
# (scripts/backfill_workout_definition_v2.py --dry-run показывает это на живой базе). Пишет только
# новые таблицы/колонки. Ни подписок, ни programs.access_level, ни планов/включений/сессий/истории —
# не касается. Версии append-only (WORKOUT_DOMAIN_V2 §5): хеш содержимого НЕ уникален в пределах
# определения (A → B → A = v1, v2, v3), уникален только (definition, version_no).
#
# downgrade: удаляет только то, что добавила эта ревизия. Откат схемы НИЖЕ этой ревизии ТЕРЯЕТ
# ДАННЫЕ (WORKOUT_DOMAIN_V2 §9.13, MIGRATION_V2 §8): вся история версий, созданная после upgrade
# (правки Builder'а, v2+, переписанные версии), удаляется вместе с таблицей. Повторный upgrade
# восстанавливает лишь то, что выводится из уцелевших V1-голов (complex_items) и замороженных
# литералов, — по одной версии на голову (+ переписанные системные); произвольная история версий
# пользователя НЕ восстанавливается в прежнем виде. Исторические строки (сессии, их
# workout_snapshot) от этих таблиц не зависят и откатом не затрагиваются.


def upgrade() -> None:
    op.create_table(
        'exercise_categories',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('parent_id', sa.BigInteger(), sa.ForeignKey('exercise_categories.id'), nullable=True),
        sa.Column('sort_order', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('is_service', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('slug', name='exercise_categories_slug_key'),
    )

    op.add_column('exercises', sa.Column('display_name', sa.String(length=255), nullable=True))
    op.add_column('exercises', sa.Column('slug', sa.String(length=64), nullable=True))
    op.add_column('exercises', sa.Column('category_id', sa.BigInteger(), nullable=True))
    op.add_column('exercises', sa.Column('subcategory_id', sa.BigInteger(), nullable=True))
    op.add_column('exercises', sa.Column('visibility', sa.String(length=16), nullable=True))
    op.add_column('exercises', sa.Column('analytics_exercise_id', sa.BigInteger(), nullable=True))
    op.create_unique_constraint('exercises_slug_key', 'exercises', ['slug'])
    op.create_foreign_key(
        'exercises_category_id_fkey', 'exercises', 'exercise_categories', ['category_id'], ['id'],
    )
    op.create_foreign_key(
        'exercises_subcategory_id_fkey', 'exercises', 'exercise_categories', ['subcategory_id'], ['id'],
    )
    op.create_foreign_key(
        'exercises_analytics_exercise_id_fkey', 'exercises', 'exercises', ['analytics_exercise_id'], ['id'],
        ondelete='SET NULL',
    )

    op.create_table(
        'workout_definition_versions',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column(
            'workout_definition_id', sa.BigInteger(),
            sa.ForeignKey('complexes.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('schema_version', sa.SmallInteger(), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('workout_definition_id', 'version_no', name='uq_wdv_definition_version_no'),
    )
    op.create_index(
        'ix_workout_definition_versions_workout_definition_id', 'workout_definition_versions',
        ['workout_definition_id'],
    )
    # Неизменяемость (AD-2) — гарантия БД, а не только дисциплина кода.
    op.execute(
        "CREATE FUNCTION workout_definition_versions_immutable() RETURNS trigger AS $$ "
        "BEGIN RAISE EXCEPTION 'workout_definition_versions rows are immutable'; END; "
        "$$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER trg_workout_definition_versions_immutable BEFORE UPDATE ON workout_definition_versions "
        "FOR EACH ROW EXECUTE FUNCTION workout_definition_versions_immutable()"
    )

    op.add_column('complexes', sa.Column('current_version_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_complexes_current_version_id', 'complexes', 'workout_definition_versions',
        ['current_version_id'], ['id'], ondelete='SET NULL',
    )

    run_backfill(op.get_bind())


def downgrade() -> None:
    op.drop_constraint('fk_complexes_current_version_id', 'complexes', type_='foreignkey')
    op.drop_column('complexes', 'current_version_id')
    op.execute("DROP TRIGGER trg_workout_definition_versions_immutable ON workout_definition_versions")
    op.execute("DROP FUNCTION workout_definition_versions_immutable()")
    op.drop_index('ix_workout_definition_versions_workout_definition_id', table_name='workout_definition_versions')
    op.drop_table('workout_definition_versions')
    op.drop_constraint('exercises_analytics_exercise_id_fkey', 'exercises', type_='foreignkey')
    op.drop_constraint('exercises_subcategory_id_fkey', 'exercises', type_='foreignkey')
    op.drop_constraint('exercises_category_id_fkey', 'exercises', type_='foreignkey')
    op.drop_constraint('exercises_slug_key', 'exercises', type_='unique')
    for column in ('analytics_exercise_id', 'visibility', 'subcategory_id', 'category_id', 'slug', 'display_name'):
        op.drop_column('exercises', column)
    op.drop_table('exercise_categories')
