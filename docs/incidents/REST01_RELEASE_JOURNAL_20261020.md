# REST01 release journal (2026-10-20)

Result: **production runs `1804a62b89660b3137a515ef97cb26ffe2100532`** (merge of PR #342; tree identical to the
rehearsed and CI-green `db35efe`, `git diff db35efe 1804a62` is empty). Includes the legacy-rest fix (#341).
Guarded apply exit 0, log `/root/backups/release-1804a62.log` on the VPS.

## Rehearsal (candidate `db35efe`, restored COPY of `prod-pre-9fb76da-20261019T203942Z.dump`)

Environment: Mac arm64, Docker Desktop linux/arm64 (8 GB), privileged `docker:dind` container (own daemon, root, `/srv`),
`deploy/rehearse-rest01-release.sh` unchanged. Dump sha256 verified (`e0342858...`); dump and reports stay on the owner's
Mac (`~/pullup-private/rest01`), not in git. Copy of the data removed afterwards.

* Control (previous runner on `d1b2375`) **reproduced the phase-8 abort**. Row diff of the backfill re-apply:
  `plan_weeks` 64 -> 123 (+59 new calendar weeks), `plan_items` 317 -> 494 (+177), `program_inclusions` 1 row changed
  (`completed_main_sessions`, `last_main_session_at`), history tables untouched. This closes the "NOT established"
  item of `REST01_BACKFILL_GUARD_DIAGNOSIS.md`.
* Target (new runner): verify-only branch taken, no backfill apply, `REHEARSAL OK`; all 52 public tables identical
  (row count + md5 of every row) before/after; `plan_weeks/plan_items/program_inclusions` identical row by row;
  independent `--verify-only`: `verified=true, errors=[], history_mutations=0, users_onboarded=61`.
* Next legacy workout (criterion 2): the real `LiveSessionService.start_session` + `engine_plan_for` for the next MAIN
  item of each of the 60 eligible legacy STEP users, inside a rolled-back transaction: candidate **60/60 = 240/180/900**
  (no user in the copy had personal values; personal values 300/210/600 are covered by
  `test_legacy_step_new_start_preserves_rest_preferences`). Negative control on prod HEAD `bd80bc9`: **0/60, all 90 s**.
  Table fingerprints identical after the probe.
* Unfinished legacy sessions with wrong rest in the copy: 0 (nothing to repair there).

## Production

* PR #342 merged (merge commit, `--match-head-commit db35efe`); no CI runs on the merge commit itself (CI is PR-only), the
  tree equals the green PR head. New runner already installed (`/root/bin/deploy-production-guarded-run.sh`, sha256
  `37d6c627...` = rehearsed).
* Preflight with defaults refused (alembic `b5d8e1f3a6c9` != default FROM `e7c2a4f9d1b3`). The documented
  continuation form is **`PROD_EXPECTED_FROM_REV=b5d8e1f3a6c9 PROD_EXPECTED_TO_REV=b5d8e1f3a6c9`** (runbook, same pair as the
  rehearsal). With it: preflight OK, apply OK (verify-only path; `will_migrate=0`, backfill migrated 0 / skipped 61;
  all phase-9 invariants OK). Downtime 17:34:33 -> 17:37:55 UTC (about 3.5 min).
* Open workouts were not touched: the only `started` session has `engine_status=cancelled`; counts before/after identical
  (users/onboarded/workouts/electives/subscriptions 99/61/74/0/81, sessions started 1 / completed 76).
* Verified after deploy: HEAD `1804a62`, `/health` ok locally and on `https://app.bimoool.com`, app/web healthy,
  `freeze_legacy_step_rest` present in both running containers, no errors in logs, alembic `b5d8e1f3a6c9`.

## Next step

1. Watch the first real legacy workout starts: read-only `legacy_rest_readonly.sql` / active-session query; expect
   240/180/900 (or the user's saved values) in new `engine_plan`s.
2. Rollback points kept (post-deploy cleanup NOT run): manifest `prod-pre-1804a62-20261020T172948Z.manifest`,
   images `local/prod-{app,web}:pre-1804a62-20261020T172948Z`.
3. Rehearsal artefacts on the owner's Mac (`~/pullup-private/rest01`: dump copy + reports) contain personal data; delete
   after the retention period.
4. Sessions already persisted with 90 s before the fix are a separate decision (none found in the copy).
