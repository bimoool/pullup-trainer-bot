"""Single history: native copy key (origin, legacy_id) and explicit superseded semantics (issue #308)

Revision ID: a7e2c5b9d1f4
Revises: f4c1a7e9b3d2
Create Date: 2026-10-10 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a7e2c5b9d1f4'
down_revision: str | None = 'f4c1a7e9b3d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DOMAIN-V2 Wave 3b (docs/domain/MIGRATION_V2.md §4, TRAINING_SESSION_V2.md §6 A6). Expand only: old code
# keeps working (its INSERTs do not know the new columns; all NULLABLE).
#   training_sessions.legacy_id          id of the legacy row (workouts.id for origin = legacy_backfill,
#                                         elective_workouts.id for origin = legacy_elective) this native copy
#                                         was converged from; NULL for native sessions.
#   training_sessions.superseded_at      explicit «this row is no longer a real workout of its own» flag.
#                                         canonical_sessions = status completed AND superseded_at IS NULL.
#                                         Replaces the per-endpoint fingerprint (_backfilled_fingerprint).
#   training_sessions.superseded_reason  legacy_deleted | legacy_replaced | native_duplicate.
#   uq_training_sessions_origin_legacy_id  UNIQUE (origin, legacy_id) WHERE legacy_id IS NOT NULL — at most one
#                                         native copy per legacy row (repeat convergence cannot duplicate).
#   ix_training_sessions_canonical        partial index for the canonical read (user, performed_at).
# superseded_by_id (f4c1a7e9b3d2) stays the optional pointer to the replacing session.
#
# No data is rewritten here: recovering legacy_id of existing copies (exact match only), creating the missing
# copies and superseding orphans is scripts/backfill_multi_program.py (dry-run by default, apply-again = 0).
# Deploy order: alembic upgrade head -> backfill --apply -> up -d.
#
# downgrade drops exactly the added index/constraints/columns. Sessions, blocks and set logs are untouched, so
# a superseded copy (its legacy row was deleted) reappears to old code as an ordinary completed session; the
# next upgrade + backfill apply re-supersedes it deterministically (legacy row absent => orphan).


def upgrade() -> None:
    op.add_column('training_sessions', sa.Column('legacy_id', sa.BigInteger(), nullable=True))
    op.add_column('training_sessions', sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('training_sessions', sa.Column('superseded_reason', sa.String(32), nullable=True))
    op.create_check_constraint(
        'ck_training_sessions_superseded_reason', 'training_sessions',
        "superseded_reason IS NULL OR superseded_reason IN ('legacy_deleted', 'legacy_replaced', 'native_duplicate')",
    )
    op.create_check_constraint(
        'ck_training_sessions_superseded_pair', 'training_sessions',
        'superseded_reason IS NULL OR superseded_at IS NOT NULL',
    )
    op.create_check_constraint(
        'ck_training_sessions_legacy_id_origin', 'training_sessions',
        "legacy_id IS NULL OR origin IN ('legacy_backfill', 'legacy_elective')",
    )
    op.create_index(
        'uq_training_sessions_origin_legacy_id', 'training_sessions', ['origin', 'legacy_id'], unique=True,
        postgresql_where=sa.text('legacy_id IS NOT NULL'),
    )
    op.create_index(
        'ix_training_sessions_canonical', 'training_sessions', ['user_id', 'performed_at'],
        postgresql_where=sa.text("status = 'completed' AND superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index('ix_training_sessions_canonical', table_name='training_sessions')
    op.drop_index('uq_training_sessions_origin_legacy_id', table_name='training_sessions')
    for name in (
        'ck_training_sessions_legacy_id_origin', 'ck_training_sessions_superseded_pair',
        'ck_training_sessions_superseded_reason',
    ):
        op.drop_constraint(name, 'training_sessions', type_='check')
    for column in ('superseded_reason', 'superseded_at', 'legacy_id'):
        op.drop_column('training_sessions', column)
