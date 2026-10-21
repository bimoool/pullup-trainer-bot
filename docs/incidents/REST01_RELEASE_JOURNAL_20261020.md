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

---

# Home → workout entry release (2026-10-20, evening)

Model: Claude Sonnet 5.5. Production now runs **`9f5cc234b1456925f6b2dff25a3607740bc0ef44`** (PR #344, tree identical to the
CI-green and staged `87f1548`); staging runs the same SHA. REST01 (`1804a62`) is contained in it.

## Actual versions found (nothing assumed)

* production `1804a62` (main), alembic `b5d8e1f3a6c9`;
* staging was **not newer**: `/home/deploy/pullup-trainer-bot-staging` ran `8263763` = `campaign/ux-ref-20261018`
  (54 commits ahead of base `e2ed40e`, 9 behind main: no REST01 fix, hence the old short rest) with two extra additive
  migrations `c7e2a9d4b1f8` (web auth tables) and `d4b7e1a9c3f5` (`custom_plans.spec`). The old clone in
  `/root/pullup-trainer-bot-staging` (`cbb5f46`, 785 behind) is a stale leftover, not the running staging.

## Root cause of "no entry from the main screen"

The Mini App Home tab is a program catalog (`HomeScreen.tsx`); the only route into a workout was a banner at the very bottom
("Готовы заниматься?") that merely switched to Plans, then "Начать" -> "Начать". Production logs show the owner starting
through `/dashboard/status` (Plans), never from Home. Not a config/URL problem: both bots open the same Mini App, the
menu button is `MINI_APP_URL` (prod `https://app.bimoool.com`, staging `https://staging.app.bimoool.com`). Reproduced
locally with main + a restored copy of the production dump (browser, signed initData): Home had no start path; Plans start
worked. Staging "worked" only because its owner-visible entry/rest state differed (old code), not because it was newer.

## Fix (PR #344, limited to the entry)

`pickHomeTraining` (`webapp-frontend/src/homeTraining.ts`) selects the first `available`, uncredited program occurrence of the
current week; Home shows a primary **"Начать тренировку"** that opens the same `PlanSessionFlow` as Plans (rest/prescription
logic untouched). If the plan says rest, Home says so with the date ("следующая с 22 окт") and links to the plan.
Tests: 5 unit tests (mutation: dropping the credited filter fails one), e2e `home-start-training.spec.ts` (V5.6, own seed
930801). The campaign branch was NOT merged and no old test version was put over REST01.

## Verification

* local (main + prod-dump copy, owner's legacy account): Home -> "Начать тренировку" -> pre-start -> start; the created
  session's engine plan has rest **240/180/900** (A/B/big break);
* CI on `87f1548`: pytest, e2e, frontend build, ruff, security, review all green; merge commit `9f5cc23` has the identical tree;
* staging (own DB `pullup_staging`, own bot `@fittest111_bot`, own token): 3 users, all V5.6; rolled-back start probe for
  the V5.6 user = 240/180/900; Home shows the rest-day notice for a user inside the spacing window; alembic
  `b5d8e1f3a6c9`, users/sessions 3/18 unchanged. No legacy-program user exists on staging, so the legacy rest check was done on the
  production copy (above and in the REST01 rehearsal), not on staging;
* production: preflight OK (`PROD_EXPECTED_FROM_REV=TO=b5d8e1f3a6c9`), guarded apply exit 0 (verify-only path, backfill
  migrated 0/skipped 61, invariants OK), downtime 18:53:56 -> 18:57:13 UTC. After: HEAD `9f5cc23`, `/health` ok locally and
  public, bundle contains the new button, `freeze_legacy_step_rest` in the running container, no log errors, data identical
  (99/61/74/0/81, sessions started 1 / completed 77, same as at preflight; the owner's own test workouts earlier today account for 74 -> 77).

## Staging changes (separate DB and tokens kept)

Backup `/home/deploy/backups/staging-pre-home-release-20261020T180359Z.dump` (+ `.sha256`), rollback image tags
`local/staging-{app,web}:pre-home-release-20261020`. Alembic downgraded `d4b7e1a9c3f5 -> b5d8e1f3a6c9` (only dropped the empty
`web_*` tables and an all-NULL `custom_plans.spec`), images built on the Mac for linux/amd64 (not on the 1 GB-class VPS
next to production) and loaded, checkout `9f5cc23`.

## Leftovers

1. The UX/auth campaign (`campaign/ux-ref-20261018`) is no longer on staging; it is intact on GitHub and needs its own
   rebase onto main + its two migrations if it is to be released.
2. Staging images were built off-server; the next staging deploy through the guarded staging script expects different
   revisions (`EXPECTED_FROM/TO_REV` in `/home/deploy/deploy-staging-guarded-run.sh` still point at the campaign line) and will
   refuse until updated.
3. Owner to confirm on a phone: Home shows "Начать тренировку" (or the rest-day notice) in the production bot. I did not
   impersonate the owner on production or start a production workout.
4. Rollback points on prod: manifest `prod-pre-9f5cc23-*.manifest`; post-deploy cleanup not run. Local artefacts with personal data
   (`~/pullup-private/rest01`) to be deleted by the owner when no longer needed.

---

# Weekly plan availability release (2026-10-21)

Model: Claude Sonnet 5.5. Production and staging run **`4deb6457c4672fdb9c8b3146d6a40fddc75a1684`** (PR #345, tree identical
to the CI-green and staged `5038a71`). Contains REST01 (240/180/900) and the Home entry (#344).

## Owner's screen, week 19-25 Oct (reproduced on a fresh read-only copy of the production DB)

API for the owner: items `[completed, too_early (from 23 Oct), infeasible (from 23 Oct)]`, `/api/dashboard` =
`gap_retest_required, days_since_last_workout = 38`, `/api/v2/dashboard/status` = `ready` (two dashboards disagreed).

## Causes (not a rules change; contract = PROJECT_SPEC "Планы v2", K1/K2)

1. **Buttons vs server availability.** `DashboardScreen.canStart` excluded only `too_early`; `infeasible` ("не успеть") kept an
   active "Начать" although the server rejects ANY main start under K1 (409 `too_early`, rule is user-level, not per item).
   The same hole existed for "Ещё раз" on a done row and for the "Сегодня" block, and `program-journey-v56.spec.ts` had pinned
   the buggy button as expected behaviour.
2. **Stale "повторный замер".** The gap/retest (`GAP_RETEST_DAYS = 35`) was measured from the last row of the legacy `workouts` table
   (13 Sep) while K1 uses legacy + native sessions (17 and 20 Oct). v2 completions do not write `workouts`, so every user who
   trains only in the Mini App would eventually get a false retest banner (bot too: `handle_start_workout` sent them into the
   re-measure flow). The v2 status used yet another source (latest session of any kind).
3. Server rest rule itself is correct and was not changed: starting any other occurrence is rejected 409 before the rest
   ends (existing tests `test_audit_opening_start_screens_is_not_a_rest_bypass`, J11; admins bypass by design, which explains
   the owner's open session 79 of 20 Oct 19:38 UTC - `ADMIN_IDS`).

## Fix

* `plan_spacing.gap_readiness(spacing)`: one "last MAIN start" (legacy + native, user timezone) for gap/retest in
  `/api/dashboard`, `/api/hello`, legacy plan context, `/api/v2/dashboard/status`, bot start.
* `planWeekNav.restBlockedUntil/canStartOccurrence` (from `plan.spacing`): while the rest runs no occurrence of the group is
  startable (row, "Ещё раз", "Сегодня"); label "Не успеть на этой неделе · старт с 23 окт". Home (`pickHomeTraining`) uses the same
  predicate and offers the same occurrence as Plans (infeasible without a rest block is startable on both, per spec section 6).
* Regressions: `test_gap_retest_counts_native_sessions_not_only_legacy_history` (fails with the fix reverted),
  `test_infeasible_occurrence_under_rest_carries_the_rest_date_and_cannot_be_started` (API contract + 409 before / 200 after the date),
  8 unit tests incl. the owner's exact week (mutation of `canStartOccurrence` fails one), e2e updated.
* After the fix on the same copy: no buttons under the rest, labels "Доступно с 23 окт" / "Не успеть ... старт с 23 окт", Home
  "Сегодня отдых ... следующая с 23 окт", `/api/dashboard` = `ready, 1 day`. REST01 4 min unchanged (engine/recipes untouched).

## Release

* CI on `5038a71`: pytest, e2e, frontend build, ruff, security, review green. Staging (own DB/bot/token, alembic `b5d8e1f3a6c9`):
  plan/spacing/dashboard consistent for the staging user (rest until 22 Oct -> `too_early`, no stale retest).
* Production: preflight OK, guarded apply `4deb645` ran phases 0-9 cleanly (verify-only path, backfill 0 migrated/61 skipped,
  invariants OK) and **failed at phase 10**: after the health URL answered, the runner read the docker health of `web` as
  `unhealthy` (the container's own healthcheck fails for ~30 s while uvicorn warms up on the 2 GB VPS under memory pressure) and
  stopped app/web as designed. Data were untouched (alembic unchanged, no restore needed). I started the already built images
  with `docker compose up -d --no-build app web` (what phase 10 does): both healthy from 06:32, public `/health` 200.
  Downtime 06:26:59 -> 06:31:07 UTC (about 4 min). Verified: HEAD `4deb645`, running image ids = the ones built by the run,
  `gap_readiness` in the container, new label in the live bundle, alembic `b5d8e1f3a6c9`, counts users 100 (one new
  registration) / onboarded 61 / workouts 74 / electives 0 / subscriptions 81 / sessions 79 unchanged.
* Staging moved to the same SHA. Rollback points: `/root/backups/prod-pre-4deb645-20261021T061833Z.manifest`, previous
  images `local/prod-{app,web}:pre-4deb645-*`; staging `local/staging-{app,web}:pre-weekly-20261021`.

## Leftovers

1. Runner phase 10 is racy on this VPS (reads container health ~1 min after `up`): same candidate passed yesterday, failed today.
   Needs a wait-for-healthy loop in `deploy/deploy-production-guarded-run.sh` (reinstall on the server + rehearsal) - not done here.
2. Admin accounts bypass K1 on the server (by design) but the UI now hides starts under the rest for them too.
3. Bot cascade (legacy `workouts`) and v2 history remain two stores; only the readiness date was unified.
4. Owner to confirm on a phone: Plans week 19-25 Oct shows no start under the rest and no re-measure banner.
5. Local artefacts with personal data (`~/pullup-private/rest01/prod-20261021.dump`) - delete when not needed.
