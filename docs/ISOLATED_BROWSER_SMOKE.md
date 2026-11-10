# Isolated browser smoke (#383)

The proposed `isolated-smoke.yml` runs a small real-browser check on pull requests,
manual runs from trusted `main`, and a best-effort `*/15` schedule after the workflow
is merged to the default branch. Preparing this workflow does not activate it or
prove a successful scheduled run. GitHub may delay or skip scheduled runs; this is
not a fifteen-minute availability SLA.

Each standard `ubuntu-latest` job has a twelve-minute limit and its own PostgreSQL
16 service, localhost-only `pullup_smoke_test`, newly generated masked signing
token, built frontend and FastAPI process. It seeds only `sweep_populated` account
996911. A target guard runs before migrations, seeding, API startup and browser
requests. PR, schedule and manual concurrency groups are independent of deployment
and shared staging. No external secret, paid API, larger runner, provisioning,
bot polling, server access or Telegram notification is used. This repository is
public; standard public-repository GitHub-hosted Ubuntu usage is currently free.
The schedule can request up to 96 jobs/day; the timeout bounds each job, but actual
runtime and GitHub usage should be checked after the first successful runs.

The dedicated config in `webapp-frontend/e2e-staging/playwright.smoke.config.ts`
uses the pure signer and explicit Android/Chromium launch contract from #384.
It imports neither the staging session fixture nor a Telegram mock. Checks cover:

- Real API accepting a signed request and rejecting missing/tampered signatures.
- Real `telegram.org/js/telegram-web-app.js` loading and `Telegram.WebApp` existing.
  Provider failure keeps the smoke red; there is no mock fallback.
- Home, Plans, Journal, Analytics and Profile, with per-screen successful API
  responses and populated landmarks, then a reload and persisted synthetic profile.
- No unexpected API failure or page exception.

The result is a source-build smoke, not a deployed-SHA check or release QA gate.
Existing full backend, frontend and E2E checks remain required. Native Telegram,
device bridges, iPhone/WebKit and production behavior are not established by this
Chromium run. See [STAGING_QA_HARNESS.md](STAGING_QA_HARNESS.md) for the separate
deployed staging and native-device obligations.

Only fixed-schema status/context and five explicitly named synthetic UI screenshots
are uploaded for three days. Screenshots are taken only after screen checks and a
diagnostic-text guard pass. No raw console, signed launch URL, headers, trace, video,
HTML/JSON Playwright report or server log is published. Raw browser/seed/server
output stays in ephemeral runner files. `context.json` distinguishes actual checkout
SHA, GitHub source SHA, workflow SHA and PR head SHA; the PR checkout is normally
GitHub's merge SHA, not the PR head. Its job status is sampled before artifact upload;
the final GitHub job conclusion remains authoritative.

Local reproduction requires the same Python dev dependencies and built frontend as
`e2e.yml`, a new isolated database and a disposable token kept outside source control:

```bash
export DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_smoke_test
export TEST_DATABASE_URL="$DATABASE_URL"
# Set BOT_TOKEN to a newly generated disposable signing token; never print it.
python scripts/isolated_smoke_guard.py
alembic upgrade head
python -m scripts.e2e_seed sweep_populated 996911
# Build webapp-frontend with npm ci && npm run build, then start:
uvicorn app.web.main:app --host 127.0.0.1 --port 8001
# From webapp-frontend/e2e-staging:
npm ci
npm run typecheck
npx playwright install chromium
npx playwright test --config playwright.smoke.config.ts
```

No remote URL override is accepted. The guard also allows localhost port 55435 for
the existing isolated cloud PostgreSQL runtime; its database name stays exact.
`E2E_CHROMIUM_PATH` and `SMOKE_PYTHON` can select already installed local binaries.

Initial local evidence (2026-11-10): migrations, seed, frontend build and TypeScript
check succeeded; eight target-guard tests passed. Removing the hostname restriction
made the unsafe-host regression fail (one failed, seven passed); restoring it returned
eight passes. Real Chromium reached the mandatory provider stage after authenticated
API 200 / missing signature 422 / tampered signature 401. The provider stage failed:
the inherited cloud proxy denied the official Telegram script with CONNECT HTTP 403.
This is a local provider blocker, not a passing browser check; GitHub Actions must
establish the full browser result before integration.
