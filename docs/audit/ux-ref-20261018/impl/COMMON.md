# Common rules for executors A, B, C

Read first: `CLAUDE.md` (project rules), `docs/AGENT_EXECUTION_MODEL.md` as in PR #340 (`git show origin/docs/navigator-brief-gates-20261018:docs/AGENT_EXECUTION_MODEL.md`),
`docs/audit/ux-ref-20261018/BACKLOG.md` (your UX-ids), `COMPLAINTS.md`, `DECISIONS.md`, your `BRIEF_<X>.md`, and for A/B `CONTRACT_A_B.md`.

## Hard limits
- Work only in **your worktree and branch**. Never touch `main`, `develop/current`, other workers' branches/files, production, the VPS, or the owner's data.
- No merge to main, no deploy, no staging deploy, no destructive git (`--force`, `reset --hard` on pushed work, `branch -D`).
- **Do not implement the 3→2 session transition for old programme connections.** Do not change `derive_slots` results for legacy snapshots, history, progression state, `completed_main_sessions`.
- Product decisions are closed (`DECISIONS.md`). Q1/Q2 defaults are proposals; Q3 (opt-in 3→2) is **out of scope**. Do not ask the owner anything; if a hard blocker appears, write it into your checkpoint file and stop.
- Schema change? Read CLAUDE.md «Изменение формулы прогрессии или схемы БД» and the `*_archive_admin_reset` rule. Expected: **no migration** in A/B/C. If you think one is needed, stop and write a contract request.
- Tests: write them for every acceptance example with **hand-computed expected values**; for every non-trivial fix show once that the test fails without the fix (revert the fix temporarily), per CLAUDE.md «Стиль тестирования». `ruff check app/ tests/` must be clean.
- **Test resources** (policy in AGENT_EXECUTION_MODEL): focused tests only (files you touched + your Playwright specs). The full suite is the coordinator's. Any dev/E2E server you start must be stopped by PID before you finish (never `pkill -f`); use ports 8021–8029 for A, 8031–8039 for B, 8041–8049 for C. Stop your test DB containers (`docker compose down` in **your** worktree) at the end.
- Python: use the shared venv `/Users/kirillv./Documents/Claude Code/.venv-ux312/bin/python` (3.12) — `source` not needed, call `.../bin/pytest` directly. Frontend: run `npm ci` inside your worktree's `webapp-frontend/` before the first build/test; `npx tsc -b && npx vite build` must pass.
- Terms: UI text Russian, concise, no internal jargon, no «A/B» Latin-vs-Cyrillic mixing (use «А»/«Б» consistently as in UX-09 — the course blocks are «Объём (А)» and «Сила (Б)»; check the existing catalogue copy and keep one spelling).

## Checkpoints (short, self-confirmed, no owner involvement)
Every 30–45 min of work or at each logical slice: `git add -A && git commit` (message ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`) and `git push -u origin <branch>`.
Append one block to `docs/audit/ux-ref-20261018/checkpoints/<worker>.md` (your own file) with: UTC time, SHA, what changed, tests run (+result), **active minutes since previous checkpoint**, **minutes waiting** (CI/builds/long test runs), **rework** (what you had to redo and why), next step. Commit it with the code.

## Finish
1. Focused tests + ruff + (B/C) `tsc -b && vite build` green.
2. Last push. Final block in your checkpoint file: summary, list of files changed, tests added (names), open risks, **exact commands the coordinator should run** to verify, `git rev-parse HEAD`.
3. Stop servers, `docker compose down` in your worktree. Do **not** remove your worktree (coordinator cleans it).
4. Final message to the coordinator: branch, HEAD SHA, 5-line summary, any blocker.
