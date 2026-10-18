# Coordinator log — implementation campaign (local session, Sonnet 5.5)

## Checkpoint 1 · 2026-10-18T11:06Z · assignments and started actions

**Base choice (project rules + facts).** `docs/AGENT_EXECUTION_MODEL.md` names `develop/current` as canonical for workers, but it is stale:
`origin/develop/current` = 1735cad (2026-10-05) is **0 ahead / 165 behind** `origin/main`; the MVP release b6c22be went out from main on 2026-10-17
(prod = main lineage) and the audit ran on main. Base = **`origin/main` e2ed40e5da46e8a2a743fd4a69f0f9e9b4d1d8e0** (verified before any edit).
Campaign branch `campaign/ux-ref-20261018` = main + audit docs (docs only; `git diff origin/main..HEAD` touches only `docs/audit/ux-ref-20261018/`) + this contract/briefs.
Prod checkout seen read-only earlier: bd80bc9 (ancestor of e2ed40e, relevant files identical).

**Other writers (verified).** 0 running Claude sessions (`list_sessions`: all `isRunning=false`), 0 pytest/uvicorn/playwright processes, no running workflows,
orchestration batch paused (#230 `orch:paused`) — **not started**. Open PR chain (#314…#334, #324) is older release-candidate work already contained in main;
`release/gating-v56-rest` (last commit 25 h ago, subscription gating + rest 60 s) is **not in main** → possible textual conflicts in `routes_v2.py`/access code; watched at integration.
Old worktrees on disk: not touched.

**Executors (new contexts, Sonnet, own worktree + branch, pushed).**
| | branch | worktree | ownership (no overlap) |
|---|---|---|---|
| A | `ux/a-availability` | `pullup-ux-a` | plan domain/services/API + tests (`plan_occurrence.py`, `plan_view.py`, `plan_convergence.py`, plan hunks of `routes_v2.py`/`schemas_v2.py`) |
| B | `ux/b-nav-electives` | `pullup-ux-b` | frontend Home/Dashboard/programme card/routing/pre-start copy, plan+elective types in `apiV2.ts`, e2e seed additions, `ux-b-*` specs |
| C | `ux/c-metrics` | `pullup-ux-c` | session summary/detail/Journal/Analytics (frontend+backend hunks), `ux-c-*` specs |
Shared files with disjoint hunks: `app/web/routes_v2.py`, `app/web/schemas_v2.py` (A vs C), `webapp-frontend/src/apiV2.ts` (B vs C) — conflicts resolved by the coordinator at integration.
Contract A↔B: `impl/CONTRACT_A_B.md` v1 (agreed before launch, additive fields only). B builds on mocks until A lands.
Rules for all: `impl/COMMON.md` (no main merge, no deploy, 3→2 transition NOT implemented, history/progression untouched, focused tests only; full gate = coordinator).

**Started:** executors launched at 2026-10-18T11:06Z (background agents; first checkpoints expected within 15 min each).
**Timing ledger (coordinator):** start of implementation = 2026-10-18T11:06Z. Active/CI/rework per worker are recorded in each `checkpoints/<X>.md`; coordinator totals at the end.

**Open access risk (staging):** staging SSH host is not discoverable from this machine (placeholder `<VPS_HOST>` in the runbook; `staging.app.bimoool.com` DNS timed out once; `192.168.1.139` in known_hosts is unreachable). The guarded dispatcher key exists (`~/.ssh/pullup_staging_guarded`). Will re-test at integration; if still unreachable → exact missing input reported as the blocker for the staging step, integrated candidate still delivered on a pushed branch.

## Result · 2026-10-18 13:28Z · integrated candidate on staging

**Candidate:** `campaign/ux-ref-20261018` @ `079022141d6aa1db8065c2549d9e890fa455fd08` (= gated `7c4416e` + removal of one generated file; code identical).
Base code: `origin/main` e2ed40e. A `9d9bf58`, B `3a79da0`, C `dd3cbf9` merged without textual conflicts; 6 integration fixes by the coordinator (below).
**Staging:** https://staging.app.bimoool.com — guarded deploy `dry-run yes -` OK 13:27:52Z (backup `/home/deploy/backups/staging-pre-0790221-20261018T132038Z.dump`, alembic unchanged `b5d8e1f3a6c9`, app/web healthy, images built by this run). Served bundle `assets/index-BtY_8oWy.js` = the bundle of the gated build; contains the new copy (checked by string search). Production untouched.

### Gate
- pytest (host): 2755 passed, 86 skipped, 4 failed = `test_prod_guarded_dispatch.py` (`flock` missing on macOS) — the same file passes 105/105 in a Linux container on main and on the candidate; `test_deploy_staging_guarded.py` (21 tests) excluded on host, passes in Linux on both trees.
- Playwright (full, `CI=1` as `e2e.yml`): 594 passed, 13 skipped, 0 failed, 1 flaky (`a11y-review` @390 dark: one 500 from `asyncpg … rejected SSL upgrade` in the local container; passed on retry). `peer-insights` 8/8.
- Baseline (clean main, same order/env): 589 passed, 9 skipped, 0 failed.
- Known unstable, also on main: `fix-wave1/first-add-to-plan` (add-to-plan sheet button «not stable / detached»; fails 4/4 in directory runs on main, 1/4 on candidate; passed in the CI-config run). Root cause not found.

### Failures found and fixed (name · cause · baseline · fix)
| Failure | Cause | Baseline | Fix |
|---|---|---|---|
| expired-course-gate ×2 | `no_access` rows lost «Начать» (leads to the subscription sheet) | green | button kept for `no_access` (`planRows.ts`) |
| ux-c-metrics ×2, `test_spec_telegram_ids_are_seeded` | C's users 930643/44 absent from `e2e_seed_all.sh` | n/a | added to seed-all |
| parity «Итог» ×12 @320 | «без длительности» at 28 px widened the tiles (scrollWidth 437) | green | smaller wrapping text style |
| parity Journal card ×4 | third child added to `.journal-card-body` (layout is two parts) | green | duration moved into the title row |
| plans-row-narrow ×2 | mock set only `state`; UI reads `start_allowed`/`blocked_reason` | green | mock sets both |
| expired-free-pullups, expired-gate (2nd run) | my run lacked `PYTHON`/DB env | green | env fixed, no code change |
| 21+4 deploy-script tests on macOS | no `flock`/`setsid` | n/a | verified in Linux |
Integration fix outside the executors' scope: legacy-schedule consequence text now also fires from the week's actual `infeasible` rows (A's real `weekly_capacity` for the legacy shape is 3, B's mock assumed 2).

### Timing (measured, not an estimate)
- Harness-measured executor runs: A 11.2 min, C 11.3 min, B 34.7 min (parallel). Their self-reported active minutes (A ≈ 80, B ≈ 140, C ≈ 90) do not match the harness durations; treat the harness numbers as the measured ones and the self-reports as unreliable.
- Coordinator: preparation (base/writers check, contract, briefs, worktrees) ≈ 25 min; integration + gate + fixes ≈ 1 h 40 min wall, of which waiting for runs ≈ 1 h (5 full E2E runs × ≈ 5.3 min, host pytest 7.6 min + one aborted, Linux containers 2 × ≈ 4.5 min, one invalid baseline attempt ×2); staging deploy 7.5 min.
- Rework: two invalid baseline runs (missing Playwright install; wrong command quoting), one hung pytest on a macOS-only test, one false signal from `--repeat-each` (shared telegram id), four fix rounds on regressions, one ssh option quoting slip.
- Launch (11:06Z) → staging OK (13:27Z): 2 h 21 min wall. Not comparable with the 25–35 engineer-day estimate (different unit: the work was done by parallel agents).

## Wave 2 · checkpoint 1 · 17:52Z · browser direction + UX editor launched

**Base:** `campaign/ux-ref-20261018` was `87383eb` (previous candidate 0790221 deployed to staging, acceptance NOT finished). Seam commit **`6cc71d42e3a3a98540c6d3d1d305ca3422dbe512`** = campaign + platform seams (`src/platform/*`: `mode.tsx`, `authBootstrap.ts`, `LoginScreen.tsx`, `session.ts`, `AppShell.tsx`, `NavBar.tsx`; `App.tsx` now delegates to them), Playwright projects `web-desktop`/`web-mobile`, plan v4, ownership table. Seam check: tsc/vite/node 369 pass; Mini App smoke 10/10 (not-onboarded, ready, telegram-back-home, session-back-button, home-discovery, mobile-layout, plans-plan-week, journal-v2).
**Executors (new contexts, Sonnet, own branch+worktree, pushed):** UX-EDITOR `ux/editor` (phase 1 = data contract + numeric examples, then stop for review), WEB-AUTH `web/auth`, WEB-LAYOUT `web/layout`. `App.tsx` is coordinator-only; seam requests go through `checkpoints/<worker>-seam-request.md`.
**Login scheme chosen: bot deep-link (device-code style)** — browser creates a request (public id + secret held only by the browser + 4-digit code, 5 min TTL), the user confirms in the bot (`from_user` of the callback, same account, no new user), the browser's poll consumes the request and receives an HttpOnly/Secure/SameSite=Lax session cookie; API calls keep the existing header with the sentinel `web-session` + cookie, so no route changes. Why not the Telegram Login Widget: it needs BotFather `/setdomain` (owner action) — documented as an alternative.
**Access check:** staging deploy path verified earlier (guarded dispatcher, host 192.241.141.47); the staging bot token/username are not available to me — the real-bot login on staging can be exercised only through the staging bot itself (owner's Telegram), automated verification uses the bot stub + test-login helper locally.

## Wave 2 · result · 2026-10-19 19:25Z · integrated candidate (Mini App + browser version), staging deploy BLOCKED on an owner step

**Candidate:** `campaign/ux-ref-20261018` code identical to `536d06b`; tip `2d3e3a4d4a0a96f9cbd98f5757870ee24572e621` (= + staging guarded script update + owner install block, no app/frontend change). Merged: WEB-AUTH `59b1cd3`, UX-EDITOR `6942e71`, WEB-LAYOUT `b2cf50a`; integration fixes by the coordinator below. Alembic: single head `d4b7e1a9c3f5` (`c7e2a9d4b1f8` web_login_requests/web_sessions → `d4b7e1a9c3f5` custom_plans.spec).

### Gate on `536d06b`
- pytest (host): **2817 passed, 86 skipped, 0 failed** (excluded on the host: `test_deploy_staging_guarded.py`, `test_prod_guarded_dispatch.py` — macOS lacks `flock`/`setsid`; in a Linux container the two + `test_deploy_production_guarded.py` pass: 170 passed, 1 skipped on 424e7c4; the updated staging-script file 67 passed, 1 skipped).
- Playwright (full, `CI=1`, projects chromium/parity/mobile/keyboard/web-desktop/web-mobile): **640 passed, 15 skipped, 0 failed**, peer-insights 8/8.
### Integration fixes (name · cause · fix)
| | cause | fix |
|---|---|---|
| duplicate migration id `c7e2a9d4b1f8` (two executors) | both picked the same id | plan-spec migration renamed `d4b7e1a9c3f5`, parent = web-auth; head-pinning tests updated |
| `test_c_second_upgrade_and_converge_are_noop`, `test_b_c_aged_db_upgrade_and_converge…` | converge ran app code on an intermediate schema lacking `custom_plans.spec` | upgrade to head before converge (equality kept) / add the column for the run (existing pattern) |
| `test_qa_fresh_reset*` ×12 | new tables `web_login_requests`/`web_sessions` not classified | classified as preserved caller identity in `qa_fresh_reset.py` |
| 12 editor tests 402 in some argv orders | pytest 9.1.1 loses `tests/test_web/conftest.py` fixtures for web files re-entered after a root-level file (UX-EDITOR root cause) | explicit trial `user` fixture in the editor test file |
| parity full-sweep ×4 | «Свободный пул» not renamed in the add-exercise picker | renamed «Без дня» |
| parity plans-schedule ×2 | move kept the row's day; new `past_day` rule refuses already-passed days (weekday-dependent) | spec picks «Без дня» |
| Wave-1 style: raw `app-shell` wrappers bypassed the shell (WEB-LAYOUT seam) | — | all full-screen branches use `AppShell`; «Войти заново» button in browser mode (WEB-AUTH seam) |
Known unstable on main too: `fix-wave1/first-add-to-plan`, `journal-sheet`/`a11y-review` (one 500 `rejected SSL upgrade` from the local Postgres container) — passed on retry or not seen in the final runs.

### Staging deploy — blocker found BEFORE touching staging
The installed guarded run-script (`/home/deploy/deploy-staging-guarded-run.sh`, owner-installed, no self-update) pins `EXPECTED_TO_REV=b5d8e1f3a6c9` and accepts only `c3f7a9e2d5b1` as the source. Staging is at `b5d8e1f3a6c9`; the candidate head is `d4b7e1a9c3f5`. A run would stop app/web, back up, build, then die in phase 6 (head check) — staging down. Preflight is read-only and does not catch it. Fixed in the repo (`deploy/deploy-staging-guarded-run.sh` accepts the previous head as source, targets the new head; tests `test_upgrades_from_the_previous_head_to_the_new_head`, `test_unknown_alembic_revision_is_refused_before_anything_stops`, Linux 67 passed). **Needs the owner to install it** (`owner-commands/install-guarded-script.txt`, sha256 `af8d2b8a56ddf39a50009e83ba4af21a1a875b95b9b247c9bd8855185bb334b0`). Mode to run afterwards: `dry-run yes -` (backup + checksum + trial restore, build, `alembic upgrade head` = both revisions in one transaction, history convergence not applied, start, health). Recovery: dump + before-manifest + saved images; code-only rollback per runbook §8.2 while convergence was not applied.

### Timing (measured)
- Harness-measured executor runs: UX-EDITOR contract 3.9 min + phase 2 ≈ 25.7 min + 16.4 min debug; WEB-AUTH ≈ 33.7 min; WEB-LAYOUT ≈ 43.7 min (parallel).
- Coordinator wave 2: seams + docs ≈ 50 min before launch; integration + gate ≈ 1 h 25 min wall (waiting on runs ≈ 55 min: 4 full E2E ≈ 5.5 min each, host pytest ≈ 11 min ×2, Linux container runs ≈ 3–4.5 min ×3).
- Rework: duplicate migration id, two test-pinned-head updates, QA-reset classification, rename/past-day spec fixes, one misdiagnosed order dependence (needed an executor), `zsh` argument splitting slips in my bisect scripts.
