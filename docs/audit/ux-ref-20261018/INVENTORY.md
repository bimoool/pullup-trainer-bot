# Access inventory (2026-10-18, cloud Claude Code session)

| Input | Status | Evidence |
|---|---|---|
| Real Crimpd (app / web / store pages) | **BLOCKED** | Egress policy of this cloud environment: `CONNECT www.crimpd.com:443 → 403 connect_rejected` (also crimpd.com, app.crimpd.com, apps.apple.com, play.google.com). No Android emulator / device in the container. |
| Our staging `staging.app.bimoool.com` / prod `app.bimoool.com` | **BLOCKED** | same egress rejection |
| Our product, local build | **AVAILABLE** | `main@e2ed40e`, FastAPI + Postgres 16 + built frontend, Chromium/Playwright, Telegram initData signed with the test token (same mechanism as `webapp-frontend/e2e`) |
| Prior reference notes | **HISTORICAL only** | `.claude/skills/crimpd-reference`, `docs/CRIMPD_FULL_PARITY_8_5.md`, `docs/audit/wave1/A-reference/*` — the wave-1 coverage file itself states “Evidence is secondhand only (no Crimpd lab, no dumps/screenshots in the repo)”. |

## Stands used

| Port | Database | Purpose |
|---|---|---|
| 8002 | `pullup_audit` — empty DB + `alembic upgrade head` only (= what a fresh deploy ships, incl. system-content migration) | fresh-user journeys (catalogue exactly as a new install) |
| 8001 | `pullup_e2e` — + `scripts/e2e_seed_all.sh` | data-rich / aged states (journal history, builder, plan stepper). Its catalogue is polluted by E2E programs, so it is NOT used for catalogue/first-run findings. |

Viewport 390×844 (and 320 for narrow checks), light + dark, `isMobile`, touch. Date of the run: Sun 18 Oct 2026 (Europe/Moscow profile).

## Limits of this environment (affect conclusions)

- **Telegram native chrome is not rendered**: BackButton / MainButton / theme come from the Telegram client.
  Screens that rely on the native BackButton (`useBackButton`, e.g. Session pre-screen) show no in-page
  back control here; this is *not* reported as a defect (INFERRED from `useBackButton.ts`: shown in Telegram).
- Not a real iPhone/Android webview: safe-area, keyboard overlap and gesture behaviour are UNKNOWN.
- Time: live-session timers were skipped with «Начать сейчас»; durations below reflect seconds, not minutes.

## Blocker (one)

**No access to the real Crimpd.** Unblock options (owner): (a) allow the Crimpd domain in this cloud
environment's network settings — only useful if a web surface exists (UNKNOWN); (b) run the reference
passes in a LOCAL session with the Android emulator / a real device (wave-1 `snap.sh` lab); (c) provide
screen recordings of the reference journeys listed in `SCENARIOS.md`. Until then every reference column is
`UNKNOWN`/`HISTORICAL`, and the gate's step 1–2 for the reference side are **not satisfied**.
