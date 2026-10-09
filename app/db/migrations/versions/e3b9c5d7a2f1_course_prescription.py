"""Course prescription: block_b.work_sets backfill, awaiting_assessment status, prescription provenance (issue #305)

Revision ID: e3b9c5d7a2f1
Revises: d8a3c6f1e2b4
Create Date: 2026-10-09 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e3b9c5d7a2f1'
down_revision: str | None = 'd8a3c6f1e2b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DOMAIN-V2 Wave 1c (docs/domain/WORKOUT_DOMAIN_V2.md §6, PROGRAM_PLAN_V2.md §3, MIGRATION_V2.md §3, §5).
# Аддитивно и совместимо со старым кодом:
#   * program_inclusions.status: varchar(16) → varchar(32) (значение «awaiting_assessment» = 19 символов);
#   * program_inclusions.prescription_provenance (JSONB, NULL — инклюзия до #305, правило не записано);
#   * progression_state.block_b.work_sets: absent/null → 4, present → untouched (MIGRATION_V2 §3).
#     4 = STRENGTH_BLOCK.work_sets на 2026-10-09 — литерал, не импорт (ревизия заморожена).
#     Остальные поля состояния (цели, снаряд, счётчики), initial_progression_state (замороженный
#     снимок), статус/курсор/ревизия, история и подписки не трогаются. Повторный прогон — 0 строк.
_STRENGTH_WORK_SETS = 4


def upgrade() -> None:
    op.alter_column(
        'program_inclusions', 'status', type_=sa.String(length=32), existing_type=sa.String(length=16),
        existing_nullable=True,
    )
    op.add_column('program_inclusions', sa.Column('prescription_provenance', postgresql.JSONB(), nullable=True))
    _backfill_block_b_work_sets()


def _backfill_block_b_work_sets() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE program_inclusions "
            "SET progression_state = jsonb_set(progression_state, '{block_b,work_sets}', CAST(:work_sets AS jsonb)) "
            "WHERE jsonb_typeof(progression_state -> 'block_b') = 'object' "
            "AND coalesce(jsonb_typeof(progression_state -> 'block_b' -> 'work_sets'), 'null') = 'null'"
        ),
        {'work_sets': str(_STRENGTH_WORK_SETS)},
    )


def downgrade() -> None:
    # block_b.work_sets остаётся (старый код читает его через role_state.get("work_sets", 1) — получает 4,
    # то есть исправленное значение); awaiting_assessment старому коду неизвестен → active.
    op.execute(
        "UPDATE program_inclusions SET status = 'active' WHERE status = 'awaiting_assessment'"
    )
    op.drop_column('program_inclusions', 'prescription_provenance')
    op.alter_column(
        'program_inclusions', 'status', type_=sa.String(length=16), existing_type=sa.String(length=32),
        existing_nullable=True,
    )
