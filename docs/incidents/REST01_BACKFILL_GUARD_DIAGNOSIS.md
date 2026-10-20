# REST01: guarded apply of the legacy-rest hotfix aborted at phase 8

## What happened (2026-10-19, run 39321135531)

Candidate `9fb76da` (no schema change, live head `b5d8e1f3a6c9`) was applied with the guarded runner.
Phases 0-7 passed, writers were stopped, the R3 dump was taken. Phase 8 ran `backfill` (apply) on a fully
migrated database (`will_migrate=0`, `already_migrated=61/61`) and then `same_legacy after-backfill` failed:
`pre-existing (legacy) data changed ... plan_items plan_weeks program_inclusions`. The runner left app/web
stopped as designed; R3 restored the pre-deploy dump (service back 20:49:07 UTC, about 6 minutes down, no data
loss: the dump was taken with writers stopped). The failed state is kept in `pullup_failed_20261019204800`.

## Diagnosis

The guard worked correctly: backfill apply is not a no-op on an already migrated database once the ISO
calendar week rolls over (the release ran on a Monday; the previous one on a Sunday). Reproduced on synthetic data
by `test_reapply_on_next_monday_moves_calendar_but_verify_only_does_not`: re-applying backfill one week later
changes `plan_weeks` and `plan_items` and leaves history untouched; dry-run and `--verify-only` change nothing.

NOT established: the exact production row diff (in particular the `program_inclusions` change). The dump and
`pullup_failed_20261019204800` on the server contain it; compare them before the next apply (see runbook).

## Fix

`scripts/backfill_multi_program.py --verify-only` plus a runner branch for "database already at the target head,
every onboarded user has a plan": verification of historical coverage runs in a server-enforced
`REPEATABLE READ, READ ONLY` transaction, before stopping writers and again (twice) after. All
full-database fingerprint, `same_legacy`, post-apply dry-run, plan-guard and invariant checks stay. Initial
migrations (a user without a plan) keep the original full backfill path. Active-session recovery is separate.

## Verification status

PostgreSQL tests for the verifier and the runner's shell flow pass in CI-equivalent runs. NOT done: rehearsal of the
exact runner on a restored copy of the production database (required before the next production apply).

## Update 2026-10-20

Rehearsal on a restored production copy done and the fix released (`1804a62`); the row diff is established
and the verify-only path ran in production. See `REST01_RELEASE_JOURNAL_20261020.md`.
