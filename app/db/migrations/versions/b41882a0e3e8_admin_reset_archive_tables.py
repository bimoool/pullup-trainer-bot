"""admin reset archive tables

Revision ID: b41882a0e3e8
Revises: 5276000c6613
Create Date: 2026-08-11 00:22:05.408508

"""
from collections.abc import Sequence

from alembic import op

revision: str = 'b41882a0e3e8'
down_revision: str | None = '5276000c6613'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Постоянные (не одноразовые, в отличие от *_archive_v1 из 34d73f5e17a4)
# архивные таблицы под админ-инструмент "🧪 Полный сброс" (см. Часть 9
# респека) — структура-клон через голый LIKE (без индексов/constraint'ов/
# identity, тот же принцип, что и раньше), без ORM-моделей: заполняются и
# читаются только через app/services/admin_reset.py напрямую SQL.
_TABLES = ("workouts", "blocks", "workout_sets", "baselines", "equipment_items")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"CREATE TABLE {table}_archive_admin_reset (LIKE {table})")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE {table}_archive_admin_reset")
