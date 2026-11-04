# Codex entry point

Read `CLAUDE.md`, `.specify/memory/constitution.md`, `docs/PROJECT_SPEC.md` and
`docs/IMPLEMENTATION_PLAN.md` before editing. Their architecture, ownership,
migration and regression-test requirements apply to Codex too.

## Restart operating rules

- Base new maintenance work on current `origin/main`, in a separate branch.
  The old `develop/current` orchestration and its October status snapshot are
  historical state. Do not restart its queue or merge it into main blindly.
- Continue an existing pushed task branch rather than duplicate it. Preserve
  unfinished changes. Concurrent writers need separate branches and worktrees.
- Keep PostgreSQL as the source of profile, history, plans and progress, shared
  by the bot and Mini App. Device caches and unsent-event queues are temporary.
- Use synthetic data and an explicit test database. Never point pytest, seed,
  convergence or rehearsal commands at production or upload production dumps.
- For a bug, demonstrate a regression failing before the fix and passing after.
  Run focused checks first, then the repository's full gates at integration.
  Date-dependent tests must cover month/week boundaries rather than assume today.
- Keep checks honest. A failing provider integration or unavailable cloud
  environment is a blocker, not a successful review. Do not disable a check,
  delete a regression, or suppress a failure to make a PR green.
- Publish code checkpoints and draft PRs. Keep detailed security investigations,
  credentials and personal data out of the public repository and CI artifacts.
- Do not deploy production, migrate infrastructure, delete user data, expand
  paid usage or accept legal terms as part of an ordinary coding task. Those
  actions require the owner's specific decision, a tested recovery plan where
  relevant, and the guarded release process.
- End each bounded cloud task with a pushed checkpoint, exact test results,
  remaining blockers and the next concrete task. No uncontrolled retry loop.

## Cloud mechanisms

Cloud server-control setup and readiness criteria: `docs/CLOUD_OPERATIONS.md`.
The operator client lives in `tools/cloud_control.py`, outside runtime images.
Prepared tooling is not proof of a connected server or successful deployment.

Codex repository review can run through the connected GitHub integration.
The manual `.github/workflows/codex-task.yml` has a `verify` mode without an LLM;
its `propose` mode is deliberately disabled until an API budget and key are
explicitly configured. It creates draft PRs after deterministic checks and
never merges or deploys. A prepared workflow is not evidence that it has run.

Follow `.claude/skills/running-tests/SKILL.md` for test setup. Guarded shell
tests requiring `setsid`, `flock` or `/proc` must run on Linux. Use existing
GitHub CI or an isolated Linux environment, not weakened macOS assertions.
