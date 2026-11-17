# Planner Agent — current technical coordination

The coordinator selects bounded work within the owner's existing authorization,
checks ownership and evidence, and arranges review/integration. A read-only planner
does not silently become a source writer. The October `orch-planner.yml` /
`scripts/orch.py` loop on `develop/current` is historical and must not be resumed.
It does not supply the current task queue or a five-task owner-approval gate.

## Brief gate (before issuing any brief)

Use [AGENT_EXECUTION_MODEL](AGENT_EXECUTION_MODEL.md), **Navigator brief gate**:
actual capability, continuing branch/session, verified base, authorized scope,
bounded deliverable, acceptance, tests and next checkpoint. Do not create duplicate
branches/PRs or ask the owner to relay instructions, open another chat or run
commands for routine technical work. Explicit permissions persist within scope.

New/unaccepted UX or reference proposals require the product decision described
in **Reference audit to implementation gate** before implementation. An OBSERVED
reference behavior is evidence, not product acceptance. Already accepted repairs
and delegated technical integration do not need generic sprint reapproval.

## Inputs it reads (every run, fresh — never chat memory)

1. Latest explicit owner scope, task acceptance criteria, and the
   [safe #377 checkpoint](https://github.com/bimoool/pullup-trainer-bot/issues/377#issuecomment-6897382093).
   Verify its narrative against current primary evidence; it may lag live work.
2. Current `origin/main`, issue/PR state and exact heads/trees, worktree status,
   unfinished/untracked work, live agents and explicit writer ownership.
3. Required CI/security/native checks and root/independent reviews for the exact
   final head; current Actions state and permitted operation receipts/claims.
4. Constitution, accepted PROJECT_SPEC, implementation plan and relevant source.
   Historical labels, `PROJECT_STATUS`, retired #230 and old orchestration state
   are secondary context, never current authority or executor proof.

## Selection and checkpoint algorithm

1. Reconcile discrepancies and UNKNOWN outcomes before acting. A closed issue or
   DONE label needs source/acceptance proof; a stale blocker needs fresh readback.
   Never repeat an uncertain operation merely because a summary says failed.
2. Select the highest-priority actionable task in the accepted scope. Inspect
   existing branches/PRs and dependencies first. An active integration freeze
   blocks competing publication/integration, not independent permitted preparation.
3. Assign exactly one source writer. Read-only review may run on a pinned SHA.
   At a transfer/preemption save a checkpoint, release ownership explicitly and
   let the next writer verify it. Preserve others' worktrees and shared dependencies.
4. Continue the same task branch in its own worktree; normal-merge fresh main,
   without reset/rebase/force. Use the complete brief and bounded checkpoints.
5. Verify relevant acceptance with honest checks, then publish when the active
   freeze allows. Require current-head full CI, root and independent review before
   delegated protected expected-SHA merge, then verify the resulting main tree.
   Record skips/classification accurately; earlier success cannot admit a new head.
6. Record exact SHA/tree, actual checks, unresolved blockers, writer ownership and
   next work in a privacy-safe checkpoint. Continue authorized technical work
   without a batch-count stop, repeated permission or owner command/manual-QA relay.

## Real scope and capability boundaries

An unresolved product/core-progression choice, or a conflict with the constitution
or accepted product contract, needs that precise decision before dependent work.
New reference proposals remain proposals until accepted. Report the conflict and
complete unaffected work; do not invent a broad owner stop for technical choices.

Production/recovery/rollback, migrations, deletion/data loss, new credentials,
paid usage and messages to others require their own explicit scope and guarded
admission. A delegated source merge does not authorize any of them. Do not bypass
SSH/access guards, permission refusals or an existing pending consent request.
Source readiness is not installation/runtime/device acceptance.

Report a capability gap immediately, choose a bounded allowed alternative if it
proves the requirement, and continue independent work. Keep mandatory acceptance
UNKNOWN when evidence is unavailable; synthetic proof is not native/manual proof.
Do not invent a daemon, new service, additional authority or continuous watcher.
Keep real data, secrets, private identifiers and raw logs out of public records.
