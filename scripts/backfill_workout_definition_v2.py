"""WorkoutDefinition v2 backfill — re-run / audit of what migration b7d2e9f4a1c3 does (issue #303).

The migration already runs the backfill on `alembic upgrade head`; this script runs EXACTLY the same
function (app.db.workout_definition_backfill.run_backfill) so an operator can see, on a live DB:
  * dry run (default): the full report, transaction ROLLED BACK — nothing written;
  * --apply: the same, committed. Idempotent: after the migration (or a previous --apply) it reports
    total_changes: 0 (MIGRATION_V2 §3 "apply-again ⇒ 0 changes").

    docker compose run --rm app python scripts/backfill_workout_definition_v2.py
    docker compose run --rm app python scripts/backfill_workout_definition_v2.py --apply

Writes only exercise_categories, the new exercises identity columns, workout_definition_versions and
complexes.current_version_id. Never touches subscriptions, access levels, plans, inclusions, sessions
or history. Flagged rows (ambiguous V1 heads) are reported, never guessed.
"""

import argparse
import asyncio
import sys

from app.db.base import async_session_factory
from app.db.workout_definition_backfill import report_lines, run_backfill


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="commit (default: dry run, rolled back)")
    args = parser.parse_args()
    async with async_session_factory() as session:
        connection = await session.connection()
        report = await connection.run_sync(run_backfill)
        if args.apply:
            await session.commit()
        else:
            await session.rollback()
    print("mode:", "apply" if args.apply else "dry-run (rolled back, nothing written)")
    for line in report_lines(report):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
