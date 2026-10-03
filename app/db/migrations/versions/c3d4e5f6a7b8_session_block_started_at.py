"""session_blocks.started_at

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-29 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# REBUILD-1 (R1): момент, когда пользователь явно начал конкретный блок
# смешанной Builder-тренировки. Аддитивно и безопасно для старого кода:
# nullable без default, ни одна существующая строка не меняется. NULL
# у старых сессий трактуется кодом как "блок 0 начат в performed_at"
# (обратная совместимость одно-блочных interval-сессий Phase B1), у новых
# блоков index > 0 — как "ещё не начат" (interstitial перед стартом).


def upgrade() -> None:
    op.add_column('session_blocks', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('session_blocks', 'started_at')
