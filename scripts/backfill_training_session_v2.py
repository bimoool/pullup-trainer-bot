"""TrainingSession v2 backfill (issue #307, docs/domain/MIGRATION_V2.md §3, TRAINING_SESSION_V2.md §2).

Revision f4c1a7e9b3d2 adds the v2 columns and fills everything derivable by literal SQL (kind, origin,
source_v2, duration, live start/end, definition ids from v1 snapshots / plan credit). This script does
the two steps that need more than SQL, plus a catch-up for rows the OLD code wrote between the
migration and the new code going live:

  1. catch-up: a row with NULL kind / origin / source_v2 / duration_source gets exactly what the
     migration would have written (same rules: app.domain.training_session_v2.legacy_source_v2 /
     legacy_duration, origin by the legacy-copy fingerprint);
  2. identity recovery (D9 history): an old «Тренировку из моих» record (source backdated, no v1
     snapshot, no definition, not yet snapshotted) gets workout_definition_id ONLY if exactly one of the
     user's own workouts (live or archived; its current items or any stored version) has the identical
     ordered exercise list — identity_recovered_by = exact_match_v1, source_v2 = manual_existing_workout.
     0 or >= 2 matches: left manual_custom and reported (never guessed);
  3. synthesized prescription_snapshot (S4) for every completed strength session without one: from its
     SetTargets, or — no target at all — from the performed sets (prescription_kind = unprescribed).
     provenance.resolved_at = performed_at, so a re-run produces byte-identical JSON.

Nothing else is written. Guards (any violation rolls the user back and exits 4, even with --apply):
the number of sessions / blocks / targets / set logs is unchanged, and per session status, performed_at,
completed_at, plan_item_id, effort, comment, activity_type and the set log values are unchanged; a
column this script fills is only ever written from NULL. Subscriptions, programs, plan rows and
progression are not read for writing.

    python scripts/backfill_training_session_v2.py               # dry run over every user (rolled back)
    python scripts/backfill_training_session_v2.py --apply       # write; a second --apply reports 0
    python scripts/backfill_training_session_v2.py --user-id 42  # one user

Exit codes: 0 ok, 4 guard violated. Output: one JSON document on stdout.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models_program import (
    Complex,
    ComplexItem,
    SessionBlock,
    SessionStatus,
    SetLog,
    SetTarget,
    TrainingSession,
    WorkoutDefinitionVersion,
)
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import SessionSource
from app.domain.training_session_v2 import (
    IDENTITY_EXACT_MATCH_V1,
    SessionKind,
    SessionOrigin,
    SessionSourceV2,
    legacy_duration,
    legacy_source_v2,
    recover_identity,
)
from app.services.training_session_v2 import TrainingSessionV2Service

EXIT_OK = 0
EXIT_GUARD = 4


@dataclass
class UserReport:
    user_id: int
    mutations: Counter = field(default_factory=Counter)
    unrecovered: list[dict] = field(default_factory=list)
    guard_violations: list[str] = field(default_factory=list)


async def _fingerprint_ids(session: AsyncSession, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    rows = await session.execute(
        select(TrainingSession.id).where(
            TrainingSession.id.in_(ids), TrainingSessionRepository._backfilled_fingerprint(),
        ),
    )
    return {row[0] for row in rows}


async def _guard_state(session: AsyncSession, user_id: int) -> dict:
    sessions = await session.execute(
        select(
            TrainingSession.id, TrainingSession.status, TrainingSession.performed_at, TrainingSession.completed_at,
            TrainingSession.plan_item_id, TrainingSession.effort, TrainingSession.comment,
            TrainingSession.activity_type,
        ).where(TrainingSession.user_id == user_id).order_by(TrainingSession.id),
    )
    session_rows = [tuple(row) for row in sessions]
    blocks = await session.scalar(
        select(func.count(SessionBlock.id)).join(TrainingSession, TrainingSession.id == SessionBlock.session_id)
        .where(TrainingSession.user_id == user_id),
    )
    targets = await session.scalar(
        select(func.count(SetTarget.id)).join(SessionBlock, SessionBlock.id == SetTarget.session_block_id)
        .join(TrainingSession, TrainingSession.id == SessionBlock.session_id).where(TrainingSession.user_id == user_id),
    )
    logs = await session.execute(
        select(SetLog.id, SetLog.value, SetLog.is_max_set, SetLog.is_extra)
        .join(SessionBlock, SessionBlock.id == SetLog.session_block_id)
        .join(TrainingSession, TrainingSession.id == SessionBlock.session_id)
        .where(TrainingSession.user_id == user_id).order_by(SetLog.id),
    )
    return {"sessions": session_rows, "blocks": blocks, "targets": targets, "logs": [tuple(r) for r in logs]}


async def _identity_candidates(session: AsyncSession, user_id: int) -> dict[int, set[tuple[int, ...]]]:
    """workout_id → known ordered exercise lists (current items + every stored version) of the user's own
    workouts, archived included."""
    workout_ids = [row[0] for row in await session.execute(
        select(Complex.id).where(Complex.source_type == "user", Complex.owner_user_id == user_id),
    )]
    candidates: dict[int, set[tuple[int, ...]]] = {wid: set() for wid in workout_ids}
    if not workout_ids:
        return candidates
    items = await session.execute(
        select(ComplexItem.complex_id, ComplexItem.exercise_id)
        .where(ComplexItem.complex_id.in_(workout_ids)).order_by(ComplexItem.complex_id, ComplexItem.order_index),
    )
    heads: dict[int, list[int]] = {}
    for complex_id, exercise_id in items:
        heads.setdefault(complex_id, []).append(exercise_id)
    for complex_id, exercise_ids in heads.items():
        candidates[complex_id].add(tuple(exercise_ids))
    versions = await session.execute(
        select(WorkoutDefinitionVersion.workout_definition_id, WorkoutDefinitionVersion.content)
        .where(WorkoutDefinitionVersion.workout_definition_id.in_(workout_ids)),
    )
    for workout_id, content in versions:
        blocks = (content or {}).get("blocks") or []
        exercise_ids = tuple(b.get("exercise_id") for b in blocks if isinstance(b, dict))
        if exercise_ids and all(isinstance(e, int) for e in exercise_ids):
            candidates[workout_id].add(exercise_ids)
    return candidates


async def backfill_user(session: AsyncSession, user_id: int) -> UserReport:
    report = UserReport(user_id=user_id)
    before = await _guard_state(session, user_id)
    rows = list((await session.execute(
        select(TrainingSession).where(TrainingSession.user_id == user_id).order_by(TrainingSession.id),
    )).scalars())
    fingerprinted = await _fingerprint_ids(session, [r.id for r in rows if r.origin is None])

    # 1. catch-up of rows the old code wrote after the migration
    for row in rows:
        if row.kind is None:
            row.kind = (SessionKind.EXTERNAL_ACTIVITY if row.activity_type else SessionKind.STRENGTH).value
            report.mutations["kind"] += 1
        if row.origin is None:
            row.origin = (
                SessionOrigin.LEGACY_ELECTIVE if row.source == SessionSource.ELECTIVE
                else SessionOrigin.LEGACY_BACKFILL if row.id in fingerprinted else SessionOrigin.NATIVE
            ).value
            report.mutations["origin"] += 1
        if row.source_v2 is None:
            row.source_v2 = legacy_source_v2(
                legacy_source=row.source.value, has_activity=row.activity_type is not None,
                has_workout_snapshot=row.workout_snapshot is not None, is_live=row.client_session_id is not None,
            ).value
            report.mutations["source_v2"] += 1
        if row.duration_source is None:
            duration = legacy_duration(
                has_activity=row.activity_type is not None, duration_seconds=row.duration_seconds,
                performed_at=row.performed_at, completed_at=row.completed_at,
            )
            row.duration_source = duration.source.value  # duration_seconds истории не переписывается
            report.mutations["duration"] += 1
    await session.flush()

    # 2. identity recovery — exact match only
    recoverable = [
        row for row in rows
        if row.source == SessionSource.BACKDATED and row.workout_snapshot is None
        and row.workout_definition_id is None and row.identity_recovered_by is None
        and row.prescription_snapshot is None and row.origin == SessionOrigin.NATIVE.value
        and row.source_v2 == SessionSourceV2.MANUAL_CUSTOM.value
    ]
    if recoverable:
        candidates = await _identity_candidates(session, user_id)
        block_rows = await session.execute(
            select(SessionBlock.session_id, SessionBlock.exercise_id, SessionBlock.complex_id)
            .where(SessionBlock.session_id.in_([r.id for r in recoverable]))
            .order_by(SessionBlock.session_id, SessionBlock.order_index),
        )
        exercises_by_session: dict[int, list[int | None]] = {}
        for session_id, exercise_id, complex_id in block_rows:
            exercises_by_session.setdefault(session_id, []).append(exercise_id if complex_id is None else None)
        for row in recoverable:
            exercise_ids = exercises_by_session.get(row.id, [])
            if any(e is None for e in exercise_ids):
                continue
            workout_id = recover_identity(exercise_ids, candidates)
            if workout_id is None:
                matches = sum(1 for lists in candidates.values() if tuple(exercise_ids) in lists)
                report.unrecovered.append({"session_id": row.id, "matches": matches})
                continue
            row.workout_definition_id = workout_id
            row.identity_recovered_by = IDENTITY_EXACT_MATCH_V1
            row.source_v2 = SessionSourceV2.MANUAL_EXISTING_WORKOUT.value
            report.mutations["identity_recovered"] += 1
        await session.flush()

    # 3. synthesized prescription snapshot (S4)
    pending = [
        row for row in rows
        if row.status == SessionStatus.COMPLETED and row.kind == SessionKind.STRENGTH.value
        and row.prescription_snapshot is None
    ]
    repo = TrainingSessionRepository(session)
    v2 = TrainingSessionV2Service(session)
    for row in pending:
        detail = await repo.get_for_user(row.id, user_id)
        snapshot = await v2.synthesized_snapshot(
            detail, workout_definition_id=row.workout_definition_id, program_inclusion_id=row.program_inclusion_id,
            resolved_at=row.performed_at,
        )
        fresh = await session.get(TrainingSession, row.id)
        fresh.prescription_snapshot = snapshot
        report.mutations["prescription_snapshot"] += 1
    await session.flush()

    after = await _guard_state(session, user_id)
    for key in ("sessions", "blocks", "targets", "logs"):
        if before[key] != after[key]:
            report.guard_violations.append(f"{key} changed")
    return report


async def run(*, apply: bool, user_id: int | None = None, session_factory=None) -> tuple[int, dict]:
    factory = session_factory or async_session_factory
    async with factory() as session:
        query = select(TrainingSession.user_id).distinct().order_by(TrainingSession.user_id)
        if user_id is not None:
            query = query.where(TrainingSession.user_id == user_id)
        user_ids = [row[0] for row in await session.execute(query)]
    totals: Counter = Counter()
    users, worst = [], EXIT_OK
    for uid in user_ids:
        async with factory() as session:
            report = await backfill_user(session, uid)
            if report.guard_violations or not apply:
                await session.rollback()
            else:
                await session.commit()
        if report.guard_violations:
            worst = EXIT_GUARD
        totals.update(report.mutations)
        if report.mutations or report.unrecovered or report.guard_violations:
            users.append({
                "user_id": uid, "mutations": dict(report.mutations), "unrecovered_identity": report.unrecovered,
                "guard_violations": report.guard_violations,
            })
    return worst, {
        "mode": "apply" if apply else "dry-run", "users": len(user_ids), "totals": dict(totals),
        "total_mutations": sum(totals.values()), "users_detail": users,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run, rolled back)")
    parser.add_argument("--user-id", type=int, default=None, help="only this users.id")
    args = parser.parse_args()
    code, report = await run(apply=args.apply, user_id=args.user_id)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
