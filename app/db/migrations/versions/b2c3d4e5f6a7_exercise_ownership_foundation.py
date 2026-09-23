"""exercise ownership foundation

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-23 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Phase C1 (issue #188) — Exercise ownership foundation, тот же паттерн,
# что Complex.source_type/owner_user_id (Phase A1, revision 5f6a7b8c9d0e):
# "system" (каталожное упражнение, доступно всем) или "user" (создано
# пользователем через будущий Workout Builder, видимо только владельцу).
# Инвариант (system -> owner_user_id IS NULL, user -> owner_user_id ==
# current_user.id) проверяется на уровне сервисного слоя, не DB CHECK —
# в проекте их нигде не используют (тот же принцип, см. Complex).
#
# Существующие строки: server_default='system' покрывает backfill без
# явного UPDATE, owner_user_id остаётся NULL по умолчанию колонки.
#
# Намеренно НЕ добавлен global UNIQUE на exercises.name — его и не было
# раньше (подтверждено чтением текущей модели и всех миграций перед этим
# решением), пользовательские "Подтягивания" от разных владельцев и от
# system должны сосуществовать без конфликта.


def upgrade() -> None:
    op.add_column(
        'exercises',
        sa.Column('source_type', sa.String(length=20), server_default='system', nullable=False),
    )
    op.add_column('exercises', sa.Column('owner_user_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_exercises_owner_user_id', 'exercises', 'users', ['owner_user_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index(op.f('ix_exercises_owner_user_id'), 'exercises', ['owner_user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_exercises_owner_user_id'), table_name='exercises')
    op.drop_constraint('fk_exercises_owner_user_id', 'exercises', type_='foreignkey')
    op.drop_column('exercises', 'owner_user_id')
    op.drop_column('exercises', 'source_type')
