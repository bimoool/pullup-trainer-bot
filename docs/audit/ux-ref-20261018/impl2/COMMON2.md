# Common rules — second wave (UX-EDITOR, WEB-AUTH, WEB-LAYOUT)

Read first: `impl/COMMON.md` (hard limits, test policy, checkpoint format — still valid; the differences below override it), `impl2/OWNERSHIP.md`,
`docs/AGENT_EXECUTION_MODEL.md` (PR #340 version: `git show origin/docs/navigator-brief-gates-20261018:docs/AGENT_EXECUTION_MODEL.md`), your brief.

## Differences from wave 1
- Checkpoint file: `docs/audit/ux-ref-20261018/checkpoints/<UX-EDITOR|WEB-AUTH|WEB-LAYOUT>.md`. Record **UTC time, SHA, active minutes, waiting minutes, rework** (measured by wall clock between your own checkpoints — do not estimate).
- Ports: UX-EDITOR 8071–8079, WEB-AUTH 8081–8089, WEB-LAYOUT 8091–8099. Local stack helper: `bash /tmp/ux_stack.sh <your worktree> <port> <db name>` (starts the worktree's compose db, migrates, seeds all, builds the frontend, starts uvicorn; prints the pid). Stop your uvicorn by PID and `docker compose down` in your worktree when finished.
- Python venv `/Users/kirillv./Documents/Claude Code/.venv-ux312/bin/`; `npm ci` in `webapp-frontend/` and in `webapp-frontend/e2e/` before the first frontend/E2E run.
- Env for E2E runs (copy exactly; the previous wave lost time on missing variables): `BOT_TOKEN=e2e-test-token ADMIN_IDS=900010,900011,900012 PYTHON=<venv>/python E2E_BASE_URL=http://127.0.0.1:<port> CI=1` plus `DATABASE_URL/POSTGRES_*` of your stack when a spec shells out to Python. **Reseed before every run** that mutates seeded users (`scripts/e2e_seed.py <scenario> <id>`).
- Full suites are the coordinator's. You run: your own specs, the specs of the screens you touched, `node --test tests/*.test.ts`, `npx tsc -b && npx vite build`, `ruff check app/ tests/`, focused pytest.
- Generated output (`test-results*`, `playwright-report`, `.env` copies) must never be committed — check `git status` before every commit (the previous wave committed one by mistake).
- **Do not weaken, skip or delete existing tests.** A spec you must change because the intended behaviour changed: change it minimally, say why in the checkpoint file.
- Never touch: `main`, production, the VPS, staging, other workers' files, the owner's data, real payments (no Robokassa live calls, no purchases; subscription checks use existing test mode/mocks only).
- **Do not implement the 3→2 transition** for older programme connections; history and progression are preserved.
- Hard blockers: write them into your checkpoint file, push, stop. Do not ask the owner.
- Finish: final block in your checkpoint file (summary, files, tests added, risks, exact verification commands, `git rev-parse HEAD`), last push, final message to the coordinator.
