# Agent Execution Model — Canonical Rules for Claude/Code Agents

This document specifies how Claude agents interact with this codebase — context isolation, model selection, parallel work boundaries, and safety practices for checkpoints and implementation.

## Fresh Context Policy

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

## Long-Running Tasks

Prefer **coherent multi-hour implementation blocks** when scope is clear (e.g., "implement Analytics v2" as one continuous session, not broken into five tiny prompts).

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

When multiple documents provide guidance:

1. **Constitution** (`.specify/memory/constitution.md`) — architectural principles, non-negotiable.
2. **PROJECT_SPEC** (`docs/PROJECT_SPEC.md`) — accepted product behavior.
3. **IMPLEMENTATION_PLAN** (`docs/IMPLEMENTATION_PLAN.md`) — what's done, what's next.
4. **ENGINEERING_NOTES** (`docs/ENGINEERING_NOTES.md`) + ADRs + skills — established practices, lessons, pitfalls.
5. **Code as fact** — actual state of implementation.
6. **Chat/memory** — lowest priority; used for context, not as source of truth.

At each level, the item above wins on conflicts. If no guidance from above, descend to the next level. If still unresolved → stop and ask the owner, do not invent.
