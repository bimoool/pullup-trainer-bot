"""training reminder settings (issue #100)

Revision ID: c2b8e6a4f1d9
Revises: b7f3a9c1e4d2
Create Date: 2026-09-13 08:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c2b8e6a4f1d9'
down_revision: str | None = 'b7f3a9c1e4d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Проактивное push-уведомление "сегодня по плану тренировка" (issue #100) —
# training_reminder_hour/training_reminder_last_sent_date следуют тому же
# принципу NULL-значит-дефолт/не-отправляли, что и a9d4e6f2b8c1
# (sound_volume_percent); training_reminder_enabled — явный тумблер с
# server_default 'false' (по умолчанию выключено). users не входит в
# список *_archive_admin_reset таблиц (см. docs/deploy.md) — архивные
# таблицы не тронуты.


def upgrade() -> None:
    op.add_column(
        'users', sa.Column('training_reminder_enabled', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column('users', sa.Column('training_reminder_hour', sa.SmallInteger(), nullable=True))
    op.add_column('users', sa.Column('training_reminder_last_sent_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'training_reminder_last_sent_date')
    op.drop_column('users', 'training_reminder_hour')
    op.drop_column('users', 'training_reminder_enabled')
