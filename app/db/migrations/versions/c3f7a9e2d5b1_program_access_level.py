"""programs.access_level — free program «Подтягивания»

Revision ID: c3f7a9e2d5b1
Revises: a4c8e1f7b2d9
Create Date: 2026-10-07 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c3f7a9e2d5b1'
down_revision: str | None = 'a4c8e1f7b2d9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Решение владельца 2026-10-07 (docs/PROJECT_SPEC.md «Подписка и доступ к курсам»; app/domain/program_access.py):
# системная программа «Подтягивания» бесплатна навсегда, остальные программы — Premium, как и были.
#
# Аддитивно и совместимо со старым кодом: новая колонка NOT NULL с server_default 'premium' — старый код её не
# читает, а его INSERT-ы получают премиум по умолчанию (ровно прежнее поведение). Данные: одна строка по
# натуральному ключу системного контента (programs.name, тот же поиск, что _ensure_program в a4c8e1f7b2d9 —
# у Program нет владельца, каталог общий). Нет программы (окружение без каталога) — ничего не меняется.
# Повторный прогон идемпотентен. Ни одной пользовательской строки не трогает.
_PROGRAM_NAME = 'Подтягивания'


def upgrade() -> None:
    op.add_column(
        'programs',
        sa.Column('access_level', sa.String(length=16), nullable=False, server_default='premium'),
    )
    op.get_bind().execute(
        sa.text(
            "UPDATE programs SET access_level = 'free' "
            "WHERE id = (SELECT id FROM programs WHERE name = :name ORDER BY id LIMIT 1)",
        ),
        {"name": _PROGRAM_NAME},
    )


def downgrade() -> None:
    op.drop_column('programs', 'access_level')
