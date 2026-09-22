"""complex protocol and ownership

Revision ID: 5f6a7b8c9d0e
Revises: 4e5f6a7b8c9d
Create Date: 2026-09-22 10:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '5f6a7b8c9d0e'
down_revision: str | None = '4e5f6a7b8c9d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Phase A1, Worker B (issue #214) — аддитивно добавить protocol storage в
# существующую Complex/ComplexItem модель. Продуктовое имя — Workout/
# WorkoutItem, техническое хранилище остаётся Complex/ComplexItem без rename.
#
# ComplexItem.protocol — произвольный JSON (Worker A параллельно определяет
# Pydantic-схему для его содержимого, здесь просто JSONB-колонка). NULL для
# legacy-записей — старые поля sets/target_value/target_unit/rest_seconds
# остаются compatibility path.
#
# Complex.source_type — "system" (каталожный комплекс, доступен всем) или
# "user" (пользовательский комплекс, привязан к owner_user_id). Инвариант
# (system → owner_user_id IS NULL, user → owner_user_id IS NOT NULL)
# проверяется на уровне сервисного/схемного слоя, не DB CHECK-констрейнтом —
# в проекте их нигде не используют (см. ProgramItem, "ровно одно из
# exercise_id/complex_id" — тот же принцип валидации сервисным слоем).


def upgrade() -> None:
    op.add_column('complex_items', sa.Column('protocol', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        'complexes',
        sa.Column('source_type', sa.String(length=20), server_default='system', nullable=False),
    )
    op.add_column('complexes', sa.Column('owner_user_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_complexes_owner_user_id', 'complexes', 'users', ['owner_user_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('fk_complexes_owner_user_id', 'complexes', type_='foreignkey')
    op.drop_column('complexes', 'owner_user_id')
    op.drop_column('complexes', 'source_type')
    op.drop_column('complex_items', 'protocol')
