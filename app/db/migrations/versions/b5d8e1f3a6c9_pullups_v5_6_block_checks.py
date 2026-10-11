"""Pull-up program V5.6: user-confirmed technique / rest per session block (issue #305)

Revision ID: b5d8e1f3a6c9
Revises: e3b9c5d7a2f1
Create Date: 2026-10-11 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b5d8e1f3a6c9'
down_revision: str | None = 'e3b9c5d7a2f1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Программа V5.6 (docs/domain/PULLUPS_V5_6.md): правила прогрессии требуют «техника по стандарту» и
# «отдых не превышал предписанного». Определить это автоматически нельзя — пользователь подтверждает явно
# на уровне блока. Аддитивно: две nullable-колонки, NULL = неизвестно (никогда не «валидно»), история не
# трогается, бэкфилла нет. Состояние V5.6 живёт в program_inclusions.progression_state (JSONB) —
# отдельной схемы не требует; старые инклюзии (без program_version) не конвертируются.


def upgrade() -> None:
    op.add_column('session_blocks', sa.Column('technique_valid', sa.Boolean(), nullable=True))
    op.add_column('session_blocks', sa.Column('rest_within_limit', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('session_blocks', 'rest_within_limit')
    op.drop_column('session_blocks', 'technique_valid')
