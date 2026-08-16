"""robokassa provider

Revision ID: 1fe2c931896d
Revises: 215e9d571a19
Create Date: 2026-08-16 10:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = '1fe2c931896d'
down_revision: str | None = '215e9d571a19'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # autogenerate не отслеживает новые значения существующих Postgres ENUM
    # (ALTER TYPE ... ADD VALUE) — добавляем вручную, тот же приём, что и в
    # 6dbcfb436c46 при добавлении 'tribute'.
    op.execute("ALTER TYPE pending_payment_provider ADD VALUE IF NOT EXISTS 'robokassa'")
    op.execute("ALTER TYPE subscription_source ADD VALUE IF NOT EXISTS 'robokassa'")


def downgrade() -> None:
    # Postgres не поддерживает удаление ОДНОГО значения ENUM (только
    # пересоздание типа целиком) — 'robokassa' остаётся и на downgrade,
    # тот же компромисс, что уже принят для 'tribute' в 6dbcfb436c46.
    pass
