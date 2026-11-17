# Agent Execution Model — Canonical Rules for Claude/Code Agents

This document governs task briefs, ownership, bounded checkpoints and verification.
It reconciles the October brief proposal with the current restart rules in
[AGENTS.md](../AGENTS.md). It does not grant permissions or activate an executor.

## Current coordination and evidence

Read current `origin/main`, the task issue and PR head before choosing work. The
[safe checkpoint in #377](https://github.com/bimoool/pullup-trainer-bot/issues/377#issuecomment-6897382093)
is an entry point, not a permanently current status record. Reconcile its claims
with fresh refs, live ownership, exact-head CI/reviews and permitted operation
receipts. An old label, successful run on another SHA or generated status mirror
cannot establish completion, authorization or current runtime state.

Carry forward explicit owner authorization within its recorded scope. Delegated
technical implementation, tests, coordination and protected integration do not
require repeated permission, owner command relay, a new chat or manual QA as a
generic prerequisite. A specific unresolved acceptance requirement still matters:
synthetic browser proof cannot be renamed physical-device or native acceptance.
Report a missing capability immediately, use a bounded permitted alternative
where it proves the same requirement, and continue independent authorized work.
Do not bypass a permission refusal or substitute unavailable evidence with a pass.

Production/recovery, rollback, schema/data migrations, deletion or possible data
loss, new credentials, paid usage and messages to others retain their separate
explicit scope and guarded admission. Existing permission persists; a source PR,
this document or an available tool does not expand it. Source readiness is not
installation, execution or runtime acceptance. Preserve claims and reconcile
UNKNOWN outcomes before any action that could repeat an operation.

## Navigator brief gate

Read these rules before assigning work. Record a concrete brief in the task or
coordinator handoff; do not make the owner carry it between tools or sessions.
Use the current environment and continue the existing task branch/session when
capable. Do not duplicate a pushed branch, PR or active writer.

```
RUN MODE: <verified local/cloud/chat capability>
MODEL: <assigned model, or unavailable; do not guess a version>
MODEL REASON: <task complexity; respect the existing assignment>
SESSION: <continue identified task, or reason for a new context>
TASK TYPE: <research/audit/implementation/documentation/release>
BASE SHA: <fresh full SHA, or N/A with reason>
BRANCH / WORKTREE: <existing task branch and exact path, or read-only>
ACCESS: <verified inputs/tools and unavailable dependencies>
AUTHORIZED ACTIONS: <existing scope, exclusions and publication holds>
DELIVERABLE: <bounded result and acceptance criteria>
TESTS / EVIDENCE: <reproduction, checks, review and remaining gates>
TIMEBOX / NEXT STATUS: <bounded milestone; separate active work from CI waits>
```

For a brief above roughly 10–15 minutes, declare intermediate checkpoints or
split independently reviewable scope; see
[worker-task-template](../.claude/skills/worker-task-template/SKILL.md).
A capability denial is a blocker to that action, not an invitation to retry
indefinitely or ask the owner for command relay. State the exact gap and the
bounded alternative. Do not promise continuous monitoring without a verified,
authorized mechanism; waiting for CI is not coding or daemon execution.

### Reference audit to implementation gate

For a new reference-driven product proposal or audit campaign:

1. Verify available reference/version and scope. Mark **OBSERVED**, **INFERRED**
   and **UNKNOWN**; screenshots, historical DONE rows and notes have bounded meaning.
2. Observe complete journeys and, where authorized and available, reproduce ours.
   Record source, scenario, actual result and missing evidence.
3. Maintain one durable backlog with stable IDs, impact, evidence, acceptance
   criteria, dependencies and confidence. Recheck findings, missing states and
   cross-screen consequences before proposing implementation slices.
4. Obtain the product decision for new/unaccepted behavior and proposed UX scope
   before implementing it. Reference OBSERVED is not an accepted product contract.
   Proposed issues such as #352/#354 do not become approved by being in a backlog.
5. Implement accepted slices and verify behavior. Existing decisions and delegated
   technical repairs need no new generic sprint approval or repeat of the entire
   reference campaign. A read-only audit remains read-only unless its scope changes.

Keep documented domain/platform differences and unresolved product choices visible.
CI green is engineering evidence, not automatic UX, device or release acceptance.

## Fresh Context Policy (implementation checkpoints)

At each bounded block, refresh branch, HEAD, worktree status, ownership and relevant
external state. Continue the existing capable session; a new context is useful
when needed for clarity, not a mandatory owner-mediated handoff. Preserve enough
durable evidence for another session to resume without chat memory.

## Chat vs. Code: Tool & Context Selection

Select tools by verified capability. Repository changes require a writable task
worktree; source review may use the connected repository tools. Planning and
explanations do not imply shell, device, server or workflow-dispatch access.
Do not send the owner to another chat or local terminal merely because a particular
capability is unavailable; finish the independent authorized work here.

## Model Routing — Escalation by Complexity

Keep the assigned model and session unless a change is explicitly authorized.
For an authorized assignment, scale reasoning to complexity: documentation and
mechanical checks are usually simple; normal implementation needs code reasoning;
architecture, races and security require deeper review. These are routing guides,
not permission to invent a model version or spawn additional writers.

## Parallel Work Boundaries

One active source writer at a time under the coordinator's ownership record.
Before transfer, save a clean checkpoint and explicitly release ownership; the
next writer verifies it afresh. A functional failure can preempt documentation
work by explicit transfer. Independent read-only review can proceed on a pinned
SHA. It must not edit the writer's checkout or silently take ownership.

Use one task branch/worktree, continue existing pushed work, and preserve unknown
or unfinished files. Separate worktrees do not themselves authorize concurrent
source writers. Never reset, rebase or force-push preserved task history to refresh
a branch; use a normal merge of current main within the authorized task scope.

## Worktree Lifecycle (mandatory)

1. **CREATE / CONTINUE** — inspect `git worktree list`, branch and status first.
   Reuse the existing task branch; a new task starts from current `origin/main`.
2. **WORK** — keep bounded commits and publish checkpoints when the coordinator's
   integration freeze permits. A held local checkpoint is prepared, not published.
3. **ACCEPT** — current checks and review, protected integration, verified main tree.
4. **CLEAN** — stop only the task's own test processes. Remove accepted worktrees
   only after proving them clean, pushed, unused and free of shared dependencies;
   never use force or delete unknown/untracked work. Uncertain means retain.

Shared dependencies remain read-only. At handoff record retained task worktrees,
unpublished work, ownership and blockers. Cleanup is not permission to touch other
workers' processes, accounts or data. See [RESOURCE_LIFECYCLE](RESOURCE_LIFECYCLE.md).

## Test Resource Policy

Use focused checks for the change before full integration gates. Reproduce bugs
before a fix, demonstrate RED → GREEN and rollback evidence as required by the
constitution. Database checks require synthetic data and an explicit isolated
PostgreSQL database; never use production for tests. Do not add tests just for activity.
Documentation-only checks validate changed links, headings, scope and semantics.

The coordinator owns the full integration gate and resource allocation. On the
final combined head, inspect all current required CI/security/native checks and
reviews; an earlier head's success cannot admit this one. Report actual workflow
classification and skips: a docs-only skip is not a full product test pass.
Investigate failures with bounded retries and fresh evidence; do not weaken
assertions, disable checks or rerun old heads to manufacture green status.

Stop only the task's own test servers by known ownership/PID. Preserve shared
dependencies and services. Privacy-safe selected evidence may be published;
real data, credentials, private investigation details and raw logs must not enter
public comments, commits or CI artifacts.

## Long-Running Tasks

Prefer scenario-based work in bounded, independently reviewable blocks. A
multi-hour campaign consists of checkpoints, not one unbounded worker run.
Each milestone records result, exact evidence, unresolved blockers and next work.
Separate active work from CI waits and unavailable access. Continue within the
existing authorized scope without a five-task stop, forced new chat or repeated
generic approval. Scope growth involving an unresolved product or separate
operational decision remains a real boundary.

## Reference-First UX

Use the accepted [PROJECT_SPEC](PROJECT_SPEC.md) and documented domain/platform
constraints. Inspect the relevant reference when the task needs it; never infer
unobserved behavior from memory. The reference gate above controls new proposals,
while accepted technical fixes retain their existing scope and acceptance criteria.

## GitHub / Checkpoint Safety

1. Commit focused changes on the existing task branch. Preserve existing history
   and untracked work; record any publication hold and the exact local checkpoint.
2. Before publication, refresh current main and PR head. Respect the coordinator's
   active integration freeze, then normally merge fresh main and publish once for
   current-head gates. Push does not imply main merge or deployment.
3. Before an authorized main merge, require root/coordinator and independent
   review of the exact combined head, resolved findings, and all current required
   gates. Use protected expected-head-SHA merge; verify the resulting main tree.
   A changed head/base or unexplained tree requires reconciliation, not blind retry.
4. Publish only privacy-safe source/CI/task evidence and a concrete next step.
   Preserve operation claims; UNKNOWN is not failed or safe to replay.

## Prompt Header Convention

Use the single header in **Navigator brief gate**, including actual base, branch,
authorization, acceptance and tests. No second abbreviated format or handoff to
the owner is required. Keep routine status updates concise and factual.

## Single Source of Truth

The repository holds the accepted product and architecture contract. Fresh GitHub
refs, source, reviews, checks and permitted primary receipts establish current
task and runtime facts. Read the latest explicit owner scope and safe checkpoint,
then verify the underlying evidence. Labels and prose snapshots cannot override
the actual head, failed/pending gates or an unknown operation outcome.

## Constitution Precedence

Within the owner's authorized scope, apply: constitution → PROJECT_SPEC →
IMPLEMENTATION_PLAN → ENGINEERING_NOTES / ADRs / skills → code as implementation
fact → historical chat/memory. A new product/core-progression decision or conflict
with the constitution requires a precise decision on that scope; do not invent it.
Routine technical choices already delegated to the coordinator do not create a
new generic owner stop. This document does not amend the constitution or product.

## Orchestration (ORCH-1) — historical only

The October `develop/current` planner/worker loop, `.github/orch/state.json`,
`.github/task/current.md`, `PROJECT_STATUS`, five-task batch and retired dashboard
#230 describe historical orchestration. Do not auto-resume it, dispatch its queue
or merge its branch into main. Old labels/keyword stop patterns do not grant or
revoke current task authorization. The [historical document](https://github.com/bimoool/pullup-trainer-bot/blob/2cff8703973bc4797a80215264abbb59a1e57af3/docs/AGENT_EXECUTION_MODEL.md)
preserves that mechanism for investigation; it is not an operating instruction.

Current coordination uses the fresh evidence and checkpoint rules above and
[PLANNER_AGENT](PLANNER_AGENT.md). Do not edit orchestration state to make an old
mirror look current or claim a prepared workflow proves an executor ran.
