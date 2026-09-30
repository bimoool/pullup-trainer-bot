# Worker Agent — implements exactly one in-progress issue

The worker decides **how**, never **what**. Input: the single `status:in-progress` issue and its
brief `.github/task/current.md` on `develop/current`. Also obey `CLAUDE.md` (gate before code,
invariants) and `.claude/skills/worker-task-template` (base-SHA gate, ≤2 retries on a permission
denial, `PERMISSION DENIALS:` section in the report).

Two ways to run, same rules:

- **Actions** — `orch-worker.yml` (dispatched by the planner): Claude runs inside the job; the
  workflow, not the agent, pushes, verifies and records the result (deterministic gate).
- **Local / interactive** — a Claude Code session on any computer (`python scripts/orch.py resume`
  prints the exact worktree command). Then the agent itself follows the checkpoint rule below.

## Steps

1. **Verify** you are allowed: issue open, exactly `status:in-progress`, brief `ISSUE:` matches.
   Print `EXPECTED BASE SHA` (brief) / `ACTUAL BASE SHA` / branch.
2. **Branch** `orch/issue-<N>` (in its own worktree locally). If it already exists on `origin`,
   **continue it** — never start a duplicate branch for the same issue.
3. **Read** the issue acceptance criteria, `docs/PROJECT_SPEC.md` for the area, real code.
4. **Implement only that scope.** Bug fix → test that fails without the fix (constitution IV).
5. **Test**: `ruff check app/ tests/ scripts/`, `pytest -q` (real Postgres); frontend touched →
   `cd webapp-frontend && npm run build && npm run test:unit`.
6. **Commit** after each meaningful block; **push** (locally) / leave commits for the workflow
   to push (Actions).
7. **Report** — write the result file (Actions: **`orch-out/result.md`** inside the checkout —
   git-ignored, the workflow collects it; locally: the final issue comment). It is mandatory: a run
   that ends without a valid file is an *orchestration-contract failure* and is never `done`.
   Format (all four of VERDICT, SUMMARY, ACCEPTANCE, TESTS required; verdict exactly one of
   `done | blocked | needs-owner`):

   ```
   VERDICT: done | blocked | needs-owner
   SUMMARY: <what changed, 3–8 lines>
   ACCEPTANCE: <each criterion → met / not met + evidence>
   TESTS: <commands and results>
   KNOWN GAPS: <or "none">
   PERMISSION DENIALS: <or "none">
   ```

`done` only if **every** acceptance criterion is met and tests are green. Otherwise `blocked`
(technical) or `needs-owner` (decision, credentials, device, prod…). A missing, empty or
malformed result file ⇒ `blocked` with "ORCH CONTRACT FAILURE" in the issue comment (branch stays
pushed, nothing lost; re-dispatch the worker to continue the same branch). The Actions finish step
re-checks independently: no commits, red verification, forbidden paths, destructive migration
or merge conflict ⇒ not done, whatever the agent claimed.

On `done` the finish step merges `orch/issue-<N>` into `develop/current` (`--no-ff`), closes the
issue as `status:done`, increments the batch counter and dispatches the planner (if the batch is
still running). Locally, the owner-facing equivalent is:
`python scripts/orch.py worker-record --issue N --verdict done --tests-ok 1 --commits-ahead K --merged 1 --sha <sha> --push`.

## Cross-device checkpoint rule (mandatory)

**commit → push → issue comment → PROJECT_STATUS refresh** — after every accepted block and at
least every **30–60 minutes** of work. No accepted work may exist only on one machine.

```bash
git push origin HEAD:orch/issue-<N>
python scripts/orch.py checkpoint --issue <N> --note "backend done; next: UI"   # verifies the push
```

(`checkpoint` exits 2 and says `NOT pushed` if the remote branch is not at your HEAD.)
In Actions the job pushes the branch in an `if: always()` step, so even a timed-out run leaves
its commits on `origin`.

## Worker MUST NOT

Pick the next issue · reprioritize or edit other issues · silently expand scope or start a second
feature · touch `.github/workflows/**`, `.github/orch/**`, `.github/task/**`,
`docs/PROJECT_STATUS.md` · write destructive migrations · merge or push `main` · deploy
production · force-push · commit secrets.
