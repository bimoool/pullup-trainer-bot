# Agent Execution Model — Canonical Rules for Claude/Code Agents

This document specifies how Claude agents interact with this codebase — context isolation, model selection, parallel work boundaries, and safety practices for checkpoints and implementation.

## Navigator brief gate (owner clarification, 2026-10-18)

Applies to every task brief, including research, audits, documentation and prompts handed to
the owner for another session. The navigator reads this document before issuing a brief;
remembering these rules or appending them only after an owner complaint is not compliance.

Every brief starts with a completed header (no unresolved placeholders handed to the owner):

```
RUN MODE: LOCAL CODE | CLOUD CODE | CHAT
MODEL: FAST / HAIKU | STANDARD / SONNET | STRONG / OPUS
MODEL REASON: <task-specific complexity; do not guess a version number>
SESSION: NEW | CONTINUE <identified existing session>
TASK TYPE: RESEARCH | AUDIT | IMPLEMENTATION | DOCUMENTATION | RELEASE
BASE SHA: <verified SHA, or N/A with reason>
BRANCH / WORKTREE: <exact target, or read-only/no checkout>
ACCESS: <verified available inputs/tools; explicitly list unverified dependencies>
DELIVERABLE: <reviewable result and acceptance evidence>
TIMEBOX: <estimated work range with assumptions>
NEXT STATUS: <concrete time and timezone or bounded first checkpoint>
AUTHORIZED ACTIONS: <reads, edits, push, merge, deployment; use existing authorization>
```

- Select LOCAL/CLOUD from actual capability, not habit. A cloud session is not assumed to have
  local reference files, an Android emulator, SSH or workflow dispatch. A local session is not
  assumed reachable when the owner is away. First verify inputs in the selected environment.
- Model choice follows the routing below. Reference capture/automation normally uses Sonnet;
  cross-product synthesis with ambiguous domain mappings may use Opus with an explicit reason.
- State NEW vs CONTINUE separately from LOCAL vs CLOUD. Continue an active release/incident in
  its existing capable session; a new independent implementation block gets fresh context.
  Do not create duplicate branches or tell the owner to find an unspecified “main session”.
- Read current GitHub refs, task state and deployment evidence. A generated status page with
  an old date is historical, not current authority. Do not silently reset orchestration state
  to match a manual release; report the discrepancy and reconcile against current issues.
- If a capability is denied, report the exact missing permission and complete unaffected work.
  Do not promise to dispatch, merge or deploy before confirming that capability.
- Estimates distinguish active work, external CI and access blockers. A control time is a
  status deadline, not an invented completion promise. Do not promise background monitoring
  without a working mechanism. Scope growth requires a revised estimate and checkpoint.

### Reference audit to implementation gate

1. Inventory and verify reference access/version. Existing notes and DONE labels are hypotheses
   until supported by observable evidence; owner screenshots seed the audit, not its boundary.
2. First pass: observe complete reference journeys, then reproduce equivalent journeys in ours.
   Record OBSERVED / INFERRED / UNKNOWN and evidence for both sides.
3. Maintain one durable backlog as findings appear: stable ID, scenario/preconditions, reference,
   actual behavior, impact, evidence, recommendation, acceptance criteria, priority, dependencies,
   and confidence/status. Product/domain differences need a documented reason, not a backend excuse.
4. Second pass: recheck findings, missing states, data/access conditions, cancellation/reload,
   narrow/wide layouts and cross-screen dependencies; deduplicate and correct the backlog.
5. Review the whole backlog and propose short, demonstrable scenario-based sprints with estimates
   and acceptance evidence. Owner review of this plan precedes implementation for this audit campaign.
6. Implement approved slices, verify behavior and visual usability, then seek release authorization
   only if not already given. CI green is engineering verification, not UX acceptance or deployment.

No app implementation during the audit. Durable evidence/backlog commits are allowed.
Functional layout (visible actions, readable controls, scrolling, weekly scheduling) is part of
the audit; final visual styling follows agreed interaction structure.

## Fresh Context Policy (implementation checkpoints)

Every accepted implementation checkpoint ends the current session context.

- A checkpoint is a **commit** with atomic, testable scope (e.g., "mixed execution" or "Analytics v2"), immediately **pushed** to its branch (push ≠ merge, push ≠ deploy).
- The next implementation task (or next checkpoint within the same task) **starts in a new Chat/Code session**.
- Reusing a long implementation context for an unrelated next block risks carrying forgotten dependencies, stale file state, or conflicting memories between tasks.

**Rationale:** Clean context boundaries prevent coupling between independent work and force explicit re-establishment of preconditions (branch, HEAD, `git status`) before each new block.

## Chat vs. Code: Tool & Context Selection

Use **Chat** for:
- Planning, design discussion, lightweight GitHub queries or status checks.
- Conceptual read-only work, exploratory questions.
- Stakeholder-facing explanations or impact assessments.

Use **Code** for:
- Repository changes (commits, pushes).
- Running commands, tests, environment setup.
- Long-running audits or investigations with file I/O.

**Implementation checkpoint implies Code:** acceptance and push always happen in Code, never left as "later do this in Chat."

## Model Routing — Escalation by Complexity

Default to **FAST / Haiku** for:
- Documentation-only edits and validation.
- GitHub hygiene: PR titles, branch creation, simple status queries.
- Mechanical edits (line-of-code, rename refactors, config updates).
- Test report collection and simple test audits.
- Non-architectural bug reports or minor fixes.

Use **STANDARD / Sonnet** for:
- Normal backend/frontend/API/React/SQLAlchemy implementation.
- Environment setup and reference automation.
- Multi-file refactors, moderate architectural changes.

Use **STRONG / Opus** for:
- Architecture design, race conditions, transaction logic.
- Security analysis, risky migrations, unclear root cause diagnostics.
- Major domain-design decisions or complex integrations.

**Escalate only when needed.** Attempt the task at the default level; if blocked by genuine architectural uncertainty or a subtle race, escalate explicitly. Do not escalate preemptively.

## Parallel Work Boundaries

Concurrent writers (multiple agents or sessions) **MUST** use:
- Separate **worktrees** (git worktree).
- Separate **branches**.
- Separate **GitHub issues/tasks** or explicit conflict-prevention strategy.

Read-only agents may inspect the same canonical commit (SHA) without worktrees.

**Never allow two coding agents to write the same checkout simultaneously.** Enforce this at task assignment time, not during the work.

## Worktree Lifecycle (mandatory)

Every concurrent writer follows four stages. A worktree that skips CLEAN is a resource leak
(2026-10: 56 worktrees, 27 forgotten uvicorn servers, a shared Postgres out of connections).

1. **CREATE** — `task → branch → worktree`. One task, one branch, one worktree
   (`git worktree add -b parallel/<task> ../pullup-par-<task> origin/develop/current`).
   Share the heavy dependencies by symlink (`.venv`, `node_modules`) instead of reinstalling.
2. **WORK** — `commit → push checkpoint` (see § GitHub / Checkpoint Safety). Pushed = preserved.
3. **ACCEPT** — review → integrate → tests → push canonical (`develop/current`).
4. **CLEAN** — as soon as a task is accepted: stop its test server, `git worktree remove <path>`
   (never `--force`), `git worktree prune`, `git branch -d <branch>` (never `-D`).
   Use `python scripts/resource_janitor.py local-clean` (dry-run by default, `--apply` to act): it
   refuses dirty, unpushed, canonical, current, in-use and shared-dependency-host worktrees.

Rules:
- A navigator **MUST clean completed worker worktrees before creating new ones**. Do not start wave
  N+1 while wave N's accepted worktrees still exist.
- At a usage-limit / session handoff the navigator **lists every retained worktree and WHY it
  remains** (active worker, unpushed work, dependency host, owner decision) in its final comment.
- Never delete a worktree that is dirty, has unpushed commits, or is used by a running process.
  Uncertain = keep, and say so.
- A worktree that hosts the shared `.venv` / `node_modules` of others is cleaned last, after its
  consumers are gone.

## Test Resource Policy

- **Parallel workers:** *focused* tests only by default — the unit/pytest files touching their change
  and the Playwright specs for their screen. They do **not** run the full suite.
- **Navigator / integration tree:** the only place for the full `pytest` + full Playwright gate.
  One browser stack at the gate, not six independent complete stacks, unless a worker's task
  technically needs one (state why in the issue comment).
- **Servers:** every E2E/dev server a run starts must die with the run. `.github/orch/e2e.sh`
  stops its own uvicorn via an `EXIT` trap (by PID, never `pkill -f`, which would kill other
  agents' servers). Local runner scripts must do the same. A server on ports 8011–8099 older than
  2 h with no owner is an orphan; `resource_janitor.py audit` lists it and `local-clean --apply`
  stops it. Shared test Postgres containers are stopped when the wave ends.
- Generated output (`playwright-report/`, `test-results/`, captures) stays out of git and is
  removed by the janitor after 3 days.

See `docs/RESOURCE_LIFECYCLE.md` for thresholds, monitoring and the VPS side.

## Long-Running Tasks

Prefer coherent scenario-based work, with bounded checkpoints. A multi-hour campaign is a plan
of independently reviewable blocks, not one unbounded worker run. For worker briefs estimated
above 10–15 minutes, split the scope or declare intermediate pushed checkpoints as required by
`.claude/skills/worker-task-template`. This rule supersedes the former recommendation to prefer
continuous multi-hour implementation blocks.

Avoid unnecessary micromanagement prompts unless:
- A checkpoint is accepted and needs explicit validation before the next phase.
- The task explicitly requires staged human decisions.
- An unexpected blocker requires re-planning.

Continuous flow within a well-defined scope is more efficient than task-switching.

## Reference-First UX

For product behavior driven by external references (Telegram API, GTO standards, official specifications):
- Inspect the actual reference before implementing, not memory.
- Mark findings as **OBSERVED** (verified against reference), **INFERRED** (deduced from code behavior), or **UNKNOWN** (unconfirmed).
- Do not invent reference behavior (e.g., "GTO categories are probably…" without checking).

**Rationale:** Mismatches between assumed and actual reference behavior are expensive, often undetected until production use.

## GitHub / Checkpoint Safety

Accepted implementation checkpoint:
1. **Code changes** committed with clear, focused message.
2. **Immediately pushed** to the branch (no "will push later").
3. Push does NOT imply merge to main or deployment.
4. **Never force-push** unless explicitly pre-approved for a specific SHA (rare).

**Rationale:** Leaving accepted work only local risks loss (git GC, accidental reset, session crash) and blocks other sessions from seeing the work. Push is the safety gate between "done locally" and "safe remotely."

## Prompt Header Convention

Canonical technical prompts (for complex implementation tasks) explicitly state:

```
RUN MODE: <mode: NEW CODE SESSION or other>
MODEL: <FAST / HAIKU | STANDARD / SONNET | STRONG / OPUS>
NEW CONTEXT REQUIRED: <YES or NO>
TASK TYPE: <IMPLEMENTATION | DOCUMENTATION | AUDIT | RESEARCH | etc.>
BASE SHA: <if creating worktree>
BRANCH / WORKTREE: <if creating new>
```

**Example:**
```
RUN MODE: NEW CODE SESSION
MODEL: STANDARD / SONNET
NEW CONTEXT REQUIRED: YES
TASK TYPE: IMPLEMENTATION
TASK: Implement Analytics v2 dashboard
BASE SHA: 830f205
BRANCH: feature/analytics-v2-dashboard
```

This header ensures the agent immediately understands scope and context without re-deriving it from scattered instructions.

## Single Source of Truth

The repository is the **only canonical source of truth** — not chat history, not memory, not external notes.

- Architectural decisions: embedded in code structure and comments.
- Product requirements: `docs/PROJECT_SPEC.md`.
- Implementation status: `docs/IMPLEMENTATION_PLAN.md` + commit history.
- Established practices/pitfalls: `docs/ENGINEERING_NOTES.md` + `.specify/memory/constitution.md`.
- Current mandatory entry point: `CLAUDE.md`.

Agents read the repository first, memory second. If memory contradicts the repository, trust the repository and update memory.

## Constitution Precedence

When multiple documents provide guidance (for executing a tracked task, the owner decision and the
issue's acceptance criteria sit on top — see *Orchestration → Precedence for a task* below):

1. **Constitution** (`.specify/memory/constitution.md`) — architectural principles, non-negotiable.
2. **PROJECT_SPEC** (`docs/PROJECT_SPEC.md`) — accepted product behavior.
3. **IMPLEMENTATION_PLAN** (`docs/IMPLEMENTATION_PLAN.md`) — what's done, what's next.
4. **ENGINEERING_NOTES** (`docs/ENGINEERING_NOTES.md`) + ADRs + skills — established practices, lessons, pitfalls.
5. **Code as fact** — actual state of implementation.
6. **Chat/memory** — lowest priority; used for context, not as source of truth.

At each level, the item above wins on conflicts. If no guidance from above, descend to the next level. If still unresolved → stop and ask the owner, do not invent.

## Orchestration (ORCH-1) — GitHub is the task state

Claude Code chats/sessions are **disposable**. Nothing needed to resume may live only in a
Claude sidebar, local memory, an unpushed branch, a local todo file or terminal scrollback.
Everything required lives in: **GitHub Issues** (labels + comments), **pushed git history**,
canonical docs, and three orchestration files on `develop/current`:

| File | Role | Written by |
|---|---|---|
| `.github/orch/state.json` | canonical branch/PR, phase, batch counter | planner / finish step / owner |
| `.github/task/current.md` | the ONE active execution brief (`ISSUE: none` when idle) | planner / finish step |
| `docs/PROJECT_STATUS.md` | short human view (+ mirrored to the pinned `orch:dashboard` issue) | `scripts/orch.py status` |

### Precedence for a task

1. explicit owner decision (issue comment/label by the owner)
2. the GitHub issue's acceptance criteria — *what* this task must do
3. constitution + this document — *how* any task must be done
4. `docs/PROJECT_SPEC.md` 5. `docs/IMPLEMENTATION_PLAN.md` 6. actual code
7. `docs/PROJECT_STATUS.md` (a generated **view**, never authority on behaviour) 8. historical docs/chat

Acceptance criteria that contradict the constitution or PROJECT_SPEC are not executed: that is
an owner stop condition (`status:needs-owner`), resolved by the owner, then the lower doc is fixed.

### Task states (labels; exactly one `status:*` per open issue)

```
status:backlog ──(owner/planner session: template complete, AC clear)──▶ status:ready
status:ready ──(planner selects; one at a time)──▶ status:in-progress
status:in-progress ──(worker: AC met, verification green, merged to develop/current)──▶ status:done + closed
status:in-progress ──(technical blocker)──▶ status:blocked
status:ready | in-progress ──(decision/credentials/device/prod/vague AC)──▶ status:needs-owner
status:blocked | needs-owner ──(owner resolves, comments)──▶ status:ready
```

Never `ready`+`in-progress`, never `in-progress`+`done`, never two open `in-progress` issues —
`python scripts/orch.py check` reports violations and the planner refuses to run on them.
Also: `priority:p0|p1|p2`, `type:bug|feature|ux|infra|qa`, `orch:owner-approved` (owner cleared a
stop-condition tripwire), `orch:dashboard` (status issue), `orch:test` (orchestrator test issues).

### Loop

**Planner** (`docs/PLANNER_AGENT.md`) → selects ONE ready issue, labels it in-progress, writes the
brief, pushes state → dispatches **Worker** (`docs/WORKER_AGENT.md`) → implements on
`orch/issue-<N>`, verification, merge to `develop/current`, labels/closes, increments batch →
dispatches **Planner** again. Actions workflows: `orch-planner.yml`, `orch-worker.yml`,
`orch-status.yml` (all `workflow_dispatch`/push on `develop/current`; see their headers).

### Batch limit

At most **5 completed** tasks (and at most 8 worker attempts) per batch. Then the batch is
`owner-review`, `PROJECT_STATUS` shows `AUTONOMOUS BATCH n: 5/5 — STOP — OWNER REVIEW REQUIRED`,
and nothing starts a sixth task. Only the owner starts a batch:
`gh workflow run orch-planner.yml --ref develop/current -f command=start-batch`
(or `python scripts/orch.py batch start --push` on develop/current). `-f command=stop-batch` stops.

### Cross-device checkpoint rule

**commit → push → issue comment → PROJECT_STATUS refresh**, after each accepted block and at
least every 30–60 min of long work (`python scripts/orch.py checkpoint --issue N --note …`).
If a machine dies, another one resumes from `origin` + the issue — never from memory.

### Resume from another computer

```bash
git clone https://github.com/bimoool/pullup-trainer-bot && cd pullup-trainer-bot   # or: git fetch
git switch develop/current && git pull
cat docs/PROJECT_STATUS.md            # or open the pinned "Project Status" issue on GitHub
python scripts/orch.py resume         # active issue, its pushed branch, exact worktree command
```

An existing pushed `orch/issue-<N>` branch is **continued**, never duplicated. Read the issue's
latest `📍 Checkpoint` / `🤖 Worker result` comment first.

### Automation (GitHub Actions) — what runs by itself

| Workflow | Trigger | Does |
|---|---|---|
| `orch-planner.yml` | `workflow_dispatch` (owner, or worker hop) | `plan` dry-run/apply, `start-batch` (owner only), `stop-batch`, `status`; dispatches the worker |
| `orch-worker.yml` | `workflow_dispatch` (planner, or owner) | Claude implements the brief → always-push → ruff/pytest/frontend + real Playwright E2E gate (E2E-relevant paths; toolchain owned by the workflow, never the agent; red gate ⇒ one auto-retry on the same branch, then blocked) → merge `--no-ff` into base → `worker-record` → dispatches planner while the batch runs |
| `orch-status.yml` | push to `develop/current`, dispatch | rewrites the pinned dashboard issue (#230) |

Level **A**: planner → worker → planner runs unattended once the owner starts a batch
(proved live on the sandbox branch, #229). Owner commands, from any computer with `gh`:

```bash
gh workflow run orch-planner.yml --ref develop/current -f command=plan                       # dry run
gh workflow run orch-planner.yml --ref develop/current -f command=start-batch               # approve batch (5)
gh workflow run orch-planner.yml --ref develop/current -f command=plan -f apply=true -f dispatch_worker=true   # go
gh workflow run orch-planner.yml --ref develop/current -f command=stop-batch                # emergency stop
```

Guards: base only `develop/current` or `orch-sandbox/*` (never `main`, no prod secrets in orch
jobs); owner-only human actor, `github-actions[bot]` only for hops; one worker at a time
(`concurrency: orch-worker`), state writers serialized (`orch-state`); hop counter ≤ 20; batch
limit 5 completed / 8 attempts; issue text never reaches a shell (brief file → agent; only the
validated issue number is interpolated); agent cannot push/merge/checkout/`gh` (post-steps do);
forbidden paths + destructive-migration grep; GITHUB_TOKEN pushes/comments trigger no workflows
(so no event loops) — only explicit dispatches chain.

Gotchas: `workflow_dispatch` only works for workflows GitHub already knows — files on `main` or
files that have had a run; each orch workflow therefore has a path-filtered `push` trigger whose
job is skipped (the skipped run registers it). A *new* branch push does not match `paths`, so a
new sandbox needs one commit that touches the workflow files. claude-code-action refuses bot
actors unless `allowed_bots: github-actions` is set. Issue templates and `claude.yml` (@claude)
are read from `main` only — they apply after an owner-approved main merge.

### ORCH-2 owner UI

Use `/orch start` / `/orch stop` on #230 or `/orch approve` on a task.
See [ORCH_OWNER_UI.md](ORCH_OWNER_UI.md). GitHub runs independently of chat/watchers.
