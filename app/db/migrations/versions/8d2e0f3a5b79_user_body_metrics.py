"""user body metrics history (weight/height)

Revision ID: 8d2e0f3a5b79
Revises: 7c1d9e2f4a68
Create Date: 2026-10-02 07:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '8d2e0f3a5b79'
down_revision: str | None = '7c1d9e2f4a68'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# История веса/роста (issue #270). Аддитивно: новая таблица, users не меняется;
# старый код её не читает. Первый деплой сидирует по одной строке из текущих
# users.weight_kg / users.height_cm (measured_at = момент миграции).


def upgrade() -> None:
    op.create_table(
        'user_body_metrics',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric', sa.String(), nullable=False),
        sa.Column('value', sa.Numeric(6, 2), nullable=False),
        sa.Column('measured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_user_body_metrics_user_id', 'user_body_metrics', ['user_id'])
    op.execute(
        "INSERT INTO user_body_metrics (user_id, metric, value, measured_at) "
        "SELECT id, 'weight_kg', weight_kg, now() FROM users WHERE weight_kg IS NOT NULL"
    )
    op.execute(
        "INSERT INTO user_body_metrics (user_id, metric, value, measured_at) "
        "SELECT id, 'height_cm', height_cm, now() FROM users WHERE height_cm IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index('ix_user_body_metrics_user_id', table_name='user_body_metrics')
    op.drop_table('user_body_metrics')
