# Planner Agent — selects exactly one next task

The planner decides **what** runs next. It never writes product code. Its deterministic core is
`scripts/orch.py plan` (unit-tested in `tests/test_orch.py`); a human or an interactive Claude
session acting as planner follows the same rules and uses the same command to apply them.

Runs: `orch-planner.yml` (GitHub Actions, `workflow_dispatch` on `develop/current`) — dispatched by
the owner, or automatically by the worker workflow after each finished task while a batch runs.

## Inputs it reads (every run, fresh — never chat memory)

1. Open issues + labels, recently closed issues (GitHub API).
2. `.github/orch/state.json` on the canonical branch — batch counter, canonical branch/PR, phase.
3. `.github/task/current.md` — the single active brief.
4. Canonical PR CI state, last worker run, staging/production deploy runs (for the status page).

## Algorithm (`plan()` in `scripts/orch.py`)

1. **Invariants.** Any open issue with >1 `status:*` label, open+`status:done`, closed+ready/
   in-progress, or more than one `status:in-progress` → **stop** (`invariant-violation`). The
   owner (or an interactive session) fixes labels; the planner does not guess.
2. **One worker at a time.** If an issue is already `status:in-progress` → `active-exists`:
   no new selection, no second worker. (A duplicate planner run is therefore a no-op.)
3. **Queue.** Open issues whose *only* status label is `status:ready`, excluding `orch:dashboard`
   (and `orch:test` outside sandbox runs). Order: `priority:p0` → `p1` → `p2` → none; within a
   priority `type:bug` first; then oldest issue number. Priority labels encode the rough policy
   *P0 bugs → release blockers → P1 UX/product → roadmap → infra → enhancements*; when issue
   context says otherwise, the owner/planner session changes the **labels**, not the code.
4. **Readiness gate** (`check_ready()`) on the WHOLE queue: first passing candidate wins; every failing one is moved
   to `status:needs-owner` with a comment giving the exact reason:
   - author is in `trusted_authors` (state.json) or the issue has `orch:owner-approved`
     (issue text becomes worker instructions — prompt-injection guard);
   - sections `Goal`, `Acceptance criteria` (≥1 list item), `Tests`, `Owner decision required`
     present (template: `.github/ISSUE_TEMPLATE/implementation.md`);
   - `Owner decision required` answer is `no`;
   - no **owner stop condition** in title/Goal/Acceptance criteria (below), unless the owner
     added `orch:owner-approved`.
5. **Batch gate.** Batch must be `running` with `completed < limit (5)` and
   `attempts < max_attempts (8)`. Otherwise → `batch-stop`; if the limit was hit, state becomes
   `owner-review` and the status page says **STOP — OWNER REVIEW REQUIRED**.
6. **Apply** (`--apply`): label `status:in-progress` (removing `status:ready`), write
   `.github/task/current.md`, comment on the issue, refresh `docs/PROJECT_STATUS.md` + dashboard
   issue, commit `chore(orch): …` to the canonical branch and push. The workflow then dispatches
   `orch-worker.yml` for that issue.

Dry run (`plan` without `--apply`) prints the same decision and changes nothing.

## Owner stop conditions → `status:needs-owner`, never invented

Ambiguous product decision · destructive migration · production deploy / main merge ·
credentials/secrets · paid external service · irreversible data operation · security-policy
decision · core progression semantics · deleting user/reference data · real-device manual
validation. Keyword patterns: `OWNER_STOP_PATTERNS` in `scripts/orch.py` (RU+EN). They are a
tripwire, not a judgement: an interactive planner session must still read the issue and move
anything ambiguous to `status:needs-owner` itself.

## Planner MUST NOT

Implement code · change product behaviour or specs · select `needs-owner`/`blocked` issues ·
choose or run a production deploy · merge `main` · exceed the batch limit · start a batch
(only the owner starts one) · trust `PROJECT_STATUS.md` over GitHub/repo (it is a view).

## Interactive planner session (Claude Code, any computer)

```bash
git fetch && git switch develop/current && git pull
python scripts/orch.py check          # invariants
python scripts/orch.py plan           # dry run — read the decision and the rejected list
# normalize issues by hand if needed: edit body to the template, set priority/type/status labels
gh workflow run orch-planner.yml --ref develop/current -f command=plan -f apply=true -f dispatch_worker=true
```
