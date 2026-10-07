# Staging QA harness

Playwright journeys that run against the **actual deployed staging** (`https://staging.app.bimoool.com`) with
realistic, dedicated QA accounts. Created after the owner's real-iPhone check failed while the local Playwright
suite (fresh DB, seeded users, mocked Telegram bridge) was green.

## Architecture

```
GitHub Actions (staging-qa.yml)                    VPS (staging only)
 ├─ job provision (optional) ── ssh forced cmd ──► ./qa-staging.sh provision|snapshot   (owner installs, see below)
 │                                                   └ docker compose -p pullup-staging run --rm app
 │                                                       python scripts/qa/provision_staging_identities.py
 └─ job journeys
     ├ curl $STAGING_URL/health  (clear failure if runners cannot reach staging)
     ├ webapp-frontend/e2e-staging  (Playwright; iPhone-14 WebKit + Pixel-7 Chromium)
     │    mint initData  = HMAC with STAGING_BOT_TOKEN (secret)  ──►  /#tgWebAppData=…  (Telegram launch URL)
     └ artifacts: report, trace (always), screenshots (always), video (on failure), /api JSON, console log
```

Files: `scripts/qa/identities.py`, `scripts/qa/mint_init_data.py`, `scripts/qa/provision_staging_identities.py`,
`webapp-frontend/e2e-staging/**`, `.github/workflows/staging-qa.yml`,
tests `tests/test_web/test_qa_mint_init_data.py`, `tests/test_web/test_qa_provision_guard.py`.

## Threat model: why there is no bypass

* App auth is **unchanged**: every request still carries `X-Telegram-Init-Data` validated by
  `app/web/auth.py` (HMAC with the bot token, 12 h max age). No debug endpoint, no flag, no test user header.
* The harness authenticates exactly as Telegram does: it signs initData with the staging bot token and opens
  the app through the Telegram launch URL (`#tgWebAppData=…&tgWebAppVersion=…&tgWebAppPlatform=ios&…`). The real
  `telegram-web-app.js` and the real frontend launch-params code run; nothing is stubbed (the local suite stubs
  `window.Telegram`, which is one reason it cannot see launch-path problems).
* Only a holder of `STAGING_BOT_TOKEN` can mint initData, same as Telegram. The token lives only in the GitHub
  secret / server env; it is masked (`::add-mask::`), never echoed, never in artifacts (the API log stores method,
  path and status only, no headers). Test: `test_cli_reads_token_only_from_env_and_never_prints_it`.
* `signature` (Ed25519) in real initData is not verified by the app; the frontend SDK requires the field, so a
  placeholder is included and covered by the HMAC. This does not weaken validation.
* QA identities are a reserved id range (`7_000_000_001..099 (5 in use)`); the provisioner refuses everything else.
* The provisioner refuses unless: `QA_ALLOW_STAGING=1`, `DATABASE_URL` db name contains `staging` (and is not
  `pullup`/`*prod*`/`*test*`), `POSTGRES_DB` agrees, `MINI_APP_URL` host starts with `staging.`, `BOT_TOKEN` set.
  Only QA ids are purged/recreated. Production is never addressed by any file here.

## QA identities

| name | telegram id | state (REAL path / SYNTHETIC part) |
|---|---|---|
| `qa_fresh_active` | 7000000001 | onboarded now via `OnboardingService`; ACTIVE sub (SYNTHETIC: `ADMIN_GRANT`, 90 d); no plan, no history |
| `qa_aged_active` | 7000000002 | onboarded 26 d ago, «Подтягивания» included from day one (`ProgramInclusionService`), plan week 1 materialised by `PlanWeekService` at the then-current date, 2 sessions in week 1 (`TrainingSessionLogService`, STEP progression). **SYNTHETIC:** timestamps back-dated (`users/training_plans/program_inclusions.created_at`), ADMIN_GRANT subscription, sessions written via the log service rather than the live UI. The current week (5) is deliberately **not** materialised: the product creates it on first open, as for the owner who last opened Plans in week 1. `--aged-days`, `--visited-weeks` vary this. |
| `qa_aged_legacy_snapshot` | 7000000005 | same as `qa_aged_active` (plan 23 d old, week 1 materialised by the real service, weeks 2..current unmaterialised) plus **one synthetic mutation, the only one beyond back-dating**: the inclusion `snapshot` loses its `"program_items"` key, the shape written by the pre-checkpoint-1.1 backfill (`scripts/backfill_multi_program.py::seed_catalog` at commit cd2808f). No PlanItem/PlanWeek is inserted or edited by hand. Current services write `program_items`, so `qa_aged_active` converges; this identity reproduces the owner's «0 из 0» (role C: H2b / H3b). |
| `qa_expired` | 7000000003 | onboarded 40 d ago, 14-day trial ended, status EXPIRED (real `refresh_status`), course still in plan |
| `qa_legacy_or_partial` | 7000000004 | legacy `Workout` rows migrated by the real backfill helpers + one legacy-only row + 2 backfilled electives (`e2e_seed.seed_journal_dedupe`) |

Ids cannot collide with `scripts/e2e_seed.py` (900001–997202, 8.1M/8.2M peers, +1M helper) or UI specs (7.4M–7.99M);
asserted in `test_qa_ids_are_reserved_and_do_not_collide_with_e2e_seed_ids`.
This mimics, it does not clone, the owner's account: if the owner's real data differs (e.g. paused inclusions, other
weeks visited), reproduce it with `--visited-weeks N` or extend the provisioner, and compare with `./qa-staging.sh snapshot` (per identity: subscription, sessions, plan weeks with item counts, and per inclusion `snapshot_has_program_items` / count).

## Journeys (`webapp-frontend/e2e-staging/specs`, run in file order; one worker)

| id | identity | what it proves |
|---|---|---|
| S-OWNER-01 | qa_aged_active **and** qa_aged_legacy_snapshot (two tests) | Plans current week has ≥1 `Начать: …` row that reaches the pre-screen, or explicit rest-week text; FORBIDS «0 из 0» + «На эту неделю пока ничего не запланировано.»; same after reload and fresh launch. Dumps `/api/v2/plan` JSON the UI received. **On a build without the #301 convergence fix the `qa_aged_legacy_snapshot` test FAILS ("DEAD END … 0 из 0") — that is the reproduction; with the fix it passes (locally verified, `docs/audit/convergence-rehearsal/`).** |
| S-OWNER-02 | qa_aged_legacy_snapshot | after the #301 convergence (runtime or `scripts/repair_plan_convergence.py`): Plans → «Начать: Подтягивания…» → pre-screen → Live → 1 set → finish → Journal → reload/relaunch, counter «N из M» with N ≥ 1. Proves the repaired account can actually train. Runbook: `docs/STAGING_CONVERGENCE_RUNBOOK.md`. |
| S-FRESH-01 | qa_fresh_active | Home → «Подтягивания» → add → Plans → Start → Live → 3 sets → Complete → Journal → Analytics → reload. UI only. Asserts the identity is really fresh first. |
| S-CUSTOM-01 | qa_fresh_active | own workout → system exercises visible without typing → nonsense search → create exercise → save → reload → direct start → complete → add to plan → reload → start from Plans |
| S-FREE-01 | qa_fresh_active | system workout «Максимум подтягиваний» started with no plan → complete → Journal (twice, with reload) |

Order matters: S-FRESH-01 must run before any other completed workout of the same identity, otherwise the product's
minimum-rest gate («Ещё рано для следующей тренировки») legitimately blocks the course start. Reprovision before every full run.
Selectors are copied from the existing local specs (`webapp-frontend/e2e/`); no new testids were invented.
Console errors, any 5xx and unexpected 4xx fail a journey (`assertClean`); retries are off on purpose.

## Running

GitHub: Actions → **Staging QA** → Run workflow (inputs `journeys`: `all` or a grep like `S-OWNER-01|S-FRESH-01`;
`reprovision`; `projects`). **`workflow_dispatch` only appears once `staging-qa.yml` is on the default branch**
(until then run it on the server or locally as below). Artifacts `staging-qa-<run id>` (14 days): `playwright-report/`,
`test-results/` (trace.zip for every test, screenshots, video on failure, `api-v2-plan-*.json`, `api-log-*.json`).

Locally / on the server (needs network to staging):
```bash
cd webapp-frontend/e2e-staging && npm ci && npx playwright install --with-deps chromium webkit
STAGING_URL=https://staging.app.bimoool.com STAGING_BOT_TOKEN=… npx playwright test            # all
STAGING_PROJECT=chromium-mobile … npx playwright test --grep S-OWNER-01
```
### Running on the server
If GitHub runners cannot reach staging (the pre-check says so), run the same commands on the VPS (or any host that can),
reading the token from `~/.staging-secrets.env`, never from the command line history.

Mint a token by hand (e.g. for manual curl): `STAGING_BOT_TOKEN=… python scripts/qa/mint_init_data.py qa_aged_active`.

## Owner: one-time actions

1. Secrets in GitHub: `STAGING_BOT_TOKEN` (exists), `VPS_HOST`, `VPS_STAGING_DEPLOY_SSH_KEY` (exist).
2. Merge `staging-qa.yml` to the default branch (dispatch availability).
3. Staging must be deployed from a ref that contains `scripts/qa/` (the `app` image copies `scripts/`).
4. Server wrapper (lives only on the VPS, not in this repo — nothing was changed there). Add one more allowed literal
   command to the forced-command dispatcher, e.g. in `authorized_keys`' wrapper:
   ```bash
   case "$SSH_ORIGINAL_COMMAND" in
     "./qa-staging.sh provision") exec /home/deploy/qa-staging.sh provision ;;
     "./qa-staging.sh snapshot")  exec /home/deploy/qa-staging.sh snapshot ;;
     # existing: ./deploy-staging.sh <branch> …
   esac
   ```
   and `/home/deploy/qa-staging.sh` (mode 755, no arguments from the client are ever passed through):
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   cd /home/deploy/pullup-trainer-bot-staging
   case "${1:-}" in
     provision) extra="" ;;
     snapshot)  extra="--snapshot" ;;
     *) echo "usage: qa-staging.sh provision|snapshot" >&2; exit 2 ;;
   esac
   docker compose -p pullup-staging run --rm -e QA_ALLOW_STAGING=1 app \
     python scripts/qa/provision_staging_identities.py $extra
   ```
   Until this exists the provision job fails with `rejected command`; run it with `reprovision=false` and provision by hand.
5. Confirm GitHub-hosted runners can reach `https://staging.app.bimoool.com/health` (nginx/firewall).

## Expected artifacts per run

`playwright-report/index.html`; per test: `trace.zip` (always), screenshots (always), `video.webm` (on failure),
`api-log-<identity>.json`, `console-errors-<identity>.json`, `api-v2-plan-<identity>.json`, `s-*-*.png`.

## Release rule

A staging-affecting fix is **DONE** only when all hold: (1) verified on the **actual staging deployment**, not a local
copy; (2) with **realistic state** (`qa_aged_active` / owner-like data, not only a fresh user); (3) via the **full UI
journey** (no DB/API shortcuts); (4) **persistence** checked (reload and fresh launch); (5) **compared with the reference**
(`product-reference`/`crimpd-reference` skills); (6) **the owner's own device check** on the real iPhone. Green CI alone,
or WebKit emulation alone, is not DONE.

## Validated where, and limits

Validated in the dev container only against a locally started backend (+built frontend) on a throwaway DB
`pullup_staging_harness`: unit tests (initData accepted by the app validator; provisioner guard), provisioner run twice
(idempotent) with snapshot, all four journeys green in Chromium (S-OWNER-01 green for `qa_aged_active`, red for `qa_aged_legacy_snapshot`). Not validated: real staging, WebKit (browser not installed
in the container), GitHub runner reachability, the SSH wrapper. The local green is not evidence about staging.


## 🧪 Fresh reset (staging) — reset your own account from Telegram (no VPS shell)

QA-only control in the **staging bot** (`app/services/qa_fresh_reset.py`, handlers in `app/bot/handlers/admin.py`):
Профиль → «🧪 Fresh reset (staging)», or the command `/qa_fresh_reset`.

* **Staging only, fail closed.** The single definition of staging is `app/services/qa_staging_guard.py`, shared
  with `provision_staging_identities.py`. The DB name in `DATABASE_URL` must contain `staging` and must not look
  like prod or test, `POSTGRES_DB` must agree with it if it is set, and the `MINI_APP_URL` host must be
  `staging.*`. The live `current_database()` must also equal the configured DB. Production never passes: the
  button is not rendered, and the command or callback answers «недоступен (<reason>)».
* **Admin only, own account only.** The caller must be in `ADMIN_IDS`, and the telegram id is taken from
  `from_user`. There is no target parameter.
* **Flow.**
  1. The first tap is a DRY RUN (rolled back). It shows rows to delete by category, the entitlement that is
     kept, and the guard status.
  2. «СБРОСИТЬ МОЙ STAGING-ПРОФИЛЬ» applies the reset.
  3. On success the bot replies `Fresh reset complete — onboarding=false / plans=0 / sessions=0 / coins=0 /
     entitlement=active`. On a guard failure it replies «НЕ выполнен — всё откатилось».
* **What is reset.** Every caller-owned row of the tables in `RESET_STEPS`:
  - v2 sessions and their children
  - plan, weeks, items, inclusions
  - own exercises and workouts, favorites
  - test results, body metrics, drafts, timers
  - coins, achievements, events
  - legacy workouts, blocks, sets, baselines, bands, electives (legacy rows are first archived into the
    existing `*_archive_admin_reset` tables)

  Every `users` column except `id/telegram_id/username/created_at/subscription_status/subscription_expires_at`
  goes back to its model default, so `onboarding_completed_at = NULL` and `coins_balance = 0`.
* **What is kept.** Identity, the entitlement, the `subscriptions` history, `pending_payments`, the system
  catalogue, collections and all other users.
* **Guards, all in one transaction.** Positively identified staging. Exactly one caller row, locked
  `FOR UPDATE`. Active entitlement before and after. Schema drift: every ORM table must be classified, the
  live DB has no unknown table, and no NOT NULL user column lacks a default. No surviving row of another user
  or of the system may reference (or CASCADE from) a caller row. Before COMMIT:
  - the caller has 0 rows everywhere, is not onboarded, and has 0 coins;
  - the entitlement is unchanged;
  - the system catalogue counts and other users' counts are unchanged.

  Any failure means ROLLBACK.
* Tests: `tests/test_services/test_qa_fresh_reset.py`, `tests/test_bot/test_qa_fresh_reset.py`.
