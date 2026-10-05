# Functional Differential Audit — Wave 1 harness (shared brief)

Umbrella issue: bimoool/pullup-trainer-bot#295. Baseline `develop/current` = `523a930`.
Repo checkout: `/home/user/pullup-trainer-bot` (branch `claude/wonderful-tesla-2dph8h` = `audit/functional-differential`, both at 523a930).

## Hard rules (all explorers)
- **AUDIT ONLY. Never edit anything under `app/`, `webapp-frontend/src/`, `scripts/` (except new files under `scripts/audit/`), migrations, or existing tests.**
  Allowed writes: your own `docs/audit/wave1/<ROLE>/` directory, `webapp-frontend/e2e/audit/<ROLE>/` (audit specs/config), `scripts/audit/<role>_*.py` (test-only helpers).
- Never repair app state to make a journey pass. Every injection of state that a real user could not create through the UI is labelled **TEST HARNESS INJECTION**, with the exact SQL/script, and never counts as a PASS of the upstream path.
- PASS = visible result after a UI action **and** still present after a reload, **and** it enables the next user action. HTTP 200 or a DB row alone is never a PASS.
- Read product code **only after a FAIL**, for diagnosis, and say so in the trace (`DIAG:`). Before a failure, use only the UI, plus the network/console that the browser exposes.
- Do not stop at the first blocker. Mark downstream steps `BLOCKED BY <F-id>` and continue the independent journeys, entering them through an alternate path (prefer another UI path, and use a labelled injection only as a last resort).
- No production or staging access. No `git push`. No `docker`. Do not touch other agents' DBs or ports.

## Environment (already running on this machine)
- Postgres 16 on `localhost:5432`, superuser `pullup:pullup`. Redis on `localhost:6379`.
- Python venv: `/home/user/pullup-trainer-bot/.venv` (Python 3.12, deps installed). Frontend already built into `webapp-frontend/dist` (served by uvicorn on the same origin).
- Playwright: `webapp-frontend/e2e/node_modules` is installed. Chromium is at `/opt/pw-browsers` (never run `playwright install`).
- Use `http://127.0.0.1:<port>`, not `localhost` (the proxy).

### Per-agent allocation
| Role | DB | Port | Redis db | Telegram ids |
|---|---|---|---|---|
| B-fresh-clean | `pullup_audit_b` (migrated, pure clean install) | 8091 | 1 | 7100001–7100099 |
| B-fresh-catalog | `pullup_audit_d` (migrated; you add the shipped catalogue via the repo's own catalogue scripts, see below) | 8092 | 2 | 7200001–7200099 |
| C-existing | `pullup_audit_c` (migrated) | 8093 | 3 | 7300001–7300099 |

Start your server (background), for example:
```bash
cd /home/user/pullup-trainer-bot
BOT_TOKEN=audit-token DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/<DB> \
REDIS_URL=redis://localhost:6379/<N> nohup .venv/bin/uvicorn app.web.main:app --host 127.0.0.1 --port <PORT> \
  > /tmp/audit-<role>-uvicorn.log 2>&1 &
```
To get a fresh DB again: `su postgres -c "dropdb <DB> && createdb -O pullup <DB>"`, then
`DATABASE_URL=... BOT_TOKEN=audit-token .venv/bin/alembic upgrade head`. Stop **your** uvicorn when you finish (`pkill -f "port <PORT>"`).

### Auth (Mini App initData)
The backend accepts `X-Telegram-Init-Data` signed with `BOT_TOKEN` (HMAC). The signing helper is `webapp-frontend/e2e/fixtures/initData.ts::buildInitData`. Inject `window.Telegram.WebApp` the way `webapp-frontend/e2e/fixtures/telegramMock.ts` and `fixtures/setup.ts` do (these are harness files, so reading them is allowed). Use `BOT_TOKEN=audit-token`.
Use an iPhone-like viewport: 390×844, light theme by default, with one dark pass for empty states.

Write audit specs under `webapp-frontend/e2e/audit/<ROLE>/` with your own `playwright.audit.config.ts` (`baseURL` = your port, `testDir` = that folder, `workers: 1`, `trace: 'on'`, `screenshot: 'on'`, output to `docs/audit/wave1/<ROLE>/artifacts/`). Run with:
`cd webapp-frontend/e2e && npx playwright test -c audit/<ROLE>/playwright.audit.config.ts`.
Exploratory scripted clicking (playwright `chromium.launch()` scripts in node) is fine too. Specs must express the journey **as a user would do it** (`getByRole` / `getByText` clicks), never `request.post` to set up state.

## Required output (your directory)
1. `TRACE.md`: for each journey assigned to you, a trace in this form:
   ```
   JOURNEY Jx — <intent>   PROFILE <name>   START STATE S0: <exact>
   10:03:12 OPEN Home
   10:03:15 TAP "Подтягивания"
   10:03:18 EXPECT Program Detail
   10:03:18 ACTUAL Program Detail            OK
   ...
   10:03:31 EXPECT >=1 workout current week
   10:03:31 ACTUAL "0 из 0" no rows           FAIL F-<ROLE>-01
   RELOAD → ...
   ```
   At each state boundary give VISIBLE STATE plus DOMAIN STATE (domain state is diagnostic and may come from SQL **after** a failure, or as a read-only check after a PASS).
2. `FINDINGS.md`: for each failure: id `F-<ROLE>-NN`, journey/step, expected, actual (verbatim UI text), evidence paths (screenshots, trace zip, console/network excerpts, API response JSON), exact repro from S0, DIAG (after failure only: API/DB/code pointer `file:line`), suggested severity (P0–P3) and likely layer. Layers: UX dead-end | missing system content | data-model gap | seed/test illusion | API/backend defect | frontend state defect | persistence defect | subscription/auth defect | plan-generation defect | execution/live-session defect | legacy/v2 convergence defect | reference-only difference | valid domain difference | platform difference | UNKNOWN.
3. `EMPTY_STATES.md` (B roles): for each of E1–E12 you reached: SCREEN | MESSAGE (verbatim) | CTA | does the CTA resolve the state? | screenshot.
4. `PROFILES.md`: how each profile was created, listing each entity as AUTH NECESSITY / DOMAIN NECESSITY / SYSTEM CONTENT / TEST CONVENIENCE. TEST CONVENIENCE is forbidden in fresh-user journeys.
5. `REACHABILITY.md`: your slice of the functional reachability tree (✅ / ❌ F-id / ⛔ BLOCKED BY / ? untested).

Russian UI text is quoted verbatim. Be factual: if you did not observe something, write UNTESTED.
