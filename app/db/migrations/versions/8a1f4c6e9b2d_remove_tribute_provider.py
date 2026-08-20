"""remove tribute provider

Revision ID: 8a1f4c6e9b2d
Revises: 1fe2c931896d
Create Date: 2026-08-20 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = '8a1f4c6e9b2d'
down_revision: str | None = '1fe2c931896d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tribute удалён из проекта (отказ в верификации продавца) — перед
    # написанием этой миграции прод-БД проверена вручную: ни одной строки
    # с provider/source='tribute' нет ни в pending_payments, ни в
    # subscriptions, так что можно убрать значение enum целиком, а не
    # оставлять как "исторический, более не используемый" источник.
    #
    # Postgres не поддерживает ALTER TYPE ... DROP VALUE — пересоздаём тип
    # целиком (rename старого -> create нового без 'tribute' -> перевести
    # колонку -> удалить старый), тот же приём, что ADD VALUE в
    # 1fe2c931896d, только в обратную сторону.
    op.execute("ALTER TYPE pending_payment_provider RENAME TO pending_payment_provider_old")
    op.execute("CREATE TYPE pending_payment_provider AS ENUM ('robokassa')")
    op.execute(
        "ALTER TABLE pending_payments ALTER COLUMN provider "
        "TYPE pending_payment_provider USING provider::text::pending_payment_provider",
    )
    op.execute("DROP TYPE pending_payment_provider_old")

    op.execute("ALTER TYPE subscription_source RENAME TO subscription_source_old")
    op.execute("CREATE TYPE subscription_source AS ENUM ('trial', 'stars', 'coins', 'admin_grant', 'robokassa')")
    op.execute(
        "ALTER TABLE subscriptions ALTER COLUMN source "
        "TYPE subscription_source USING source::text::subscription_source",
    )
    op.execute("DROP TYPE subscription_source_old")


def downgrade() -> None:
    op.execute("ALTER TYPE pending_payment_provider RENAME TO pending_payment_provider_new")
    op.execute("CREATE TYPE pending_payment_provider AS ENUM ('tribute', 'robokassa')")
    op.execute(
        "ALTER TABLE pending_payments ALTER COLUMN provider "
        "TYPE pending_payment_provider USING provider::text::pending_payment_provider",
    )
    op.execute("DROP TYPE pending_payment_provider_new")

    op.execute("ALTER TYPE subscription_source RENAME TO subscription_source_new")
    op.execute(
        "CREATE TYPE subscription_source AS ENUM "
        "('trial', 'stars', 'coins', 'admin_grant', 'tribute', 'robokassa')",
    )
    op.execute(
        "ALTER TABLE subscriptions ALTER COLUMN source "
        "TYPE subscription_source USING source::text::subscription_source",
    )
    op.execute("DROP TYPE subscription_source_new")
