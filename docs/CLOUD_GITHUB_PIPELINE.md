# One-chat GitHub coordination: guarded release commands

The coordinator stays in the main chat. GitHub holds service task briefs, PRs,
executor commits and CI receipts. A GitHub Codex reaction is not completion.
Do not enable API-backed `codex-task.yml propose`, extra credits or the old
`develop/current` queue. Server keys remain in GitHub Secrets.

## Fixed server commands

After review and owner-authorized merge to the trusted default branch, the owner
or the owner's authorized GitHub connection in the main chat can post exactly:

```
/pullup staging-preflight <40-character-lowercase-current-PR-head-SHA>
```

An open or merged same-repository `codex/` PR targeting `main` is eligible.
Closed unmerged PRs are refused. PR372 and PR374 remain excluded; use the reviewed
integration PR containing the final release tools and product tree. Commands
always use that PR's exact head SHA, including after its merge. Keep the branch.

The owner requested the live release in issue #377. The command adapter now
supports these fixed commands, with no arbitrary workflow, URL or shell input:

| Command after `/pullup ` | Fixed action |
| --- | --- |
| `staging-preflight SHA` | Guarded staging, `preflight`, `start=no`, `users=-` |
| `rehearse SHA` | Existing synthetic Docker rehearsal on the PR branch; verify the actual run SHA |
| `staging-deploy SHA` | Guarded staging, `dry-run`, `start=yes`, `users=-` |
| `staging-qa SHA` | Fixed current-v2 release suite (06/07) in Chromium and WebKit, freshly provisioned per browser |
| `production-preflight SHA FROM TO` | Existing guarded production workflow, preflight only |
| `production-apply SHA FROM TO PRODUCTION-APPLY-SHA12` | Existing guarded production apply with its exact confirmation |
| `rollback-check SHA R1_OR_R3 MANIFEST` | Existing rollback inspection, `mode=check` only |

`SHA` is 40 lowercase hex characters; `FROM` and `TO` are 12-character observed
Alembic revisions, not invented defaults. `SHA12` is the candidate's first12
characters. The manifest must be a safe `/root/backups/*.manifest` path from the
actual guarded deployment. Rollback apply is deliberately not automated here:
R3 can lose activity since the backup and needs a separate recovery decision.

**staging-deploy is state-changing.** It stops services, backs up, builds,
upgrades to the existing Alembic head and starts verified services. Its fixed
`dry-run` mode means convergence is inspected, not applied; this is not a
read-only deployment. No history-convergence apply or arbitrary user list is
accepted. QA reprovisioning remains limited by the existing staging identity guard.

Every release operation requires all exact-SHA product checks, plus rehearsal
(the rehearsal command itself requires the other six checks). Mutating release
operations also require the candidate tree to equal current trusted main.
QA requires a successful latest staging deployment of this exact candidate.
Only `release-qa.yml` can supply release evidence: it has no journey/project
filter inputs, runs both browsers sequentially with separate provisioning,
and executes complete current-v2 files 06/07 with zero retries. Diagnostic
`staging-qa.yml` runs cannot satisfy the gate, even with the same candidate SHA.
The larger functional suite remains independently required by CI `e2e`.
Production apply additionally requires successful fixed release QA after that
deployment and a successful matching production preflight after QA and within
the last hour. Run titles bind the SHA, fixed QA suite and modes/revisions to reviewed workflow
inputs; an older success cannot replace a newer failed matching run. The adapter
does not substitute these records for actual Telegram/iPhone acceptance or the
remaining runbook go/no-go items: the coordinator must finish those before
posting production apply.

All server operations dispatch reviewed workflows at `ref=main`. Only the
secret-free rehearsal uses the reviewed PR branch to test its exact commit.
The adapter receives no server key or runtime PAT. Existing forced-command SSH,
production environment protections, backups, checks and rollback rules remain.

The adapter validates repository name/ID, owner ID/login, sender, association,
live comment, current PR head, base/head repository and active workflow. It
checks out only `github.workflow_sha` from trusted `main`, never PR code.
Commands are read as JSON, never evaluated by a shell. No user-supplied URL,
workflow filename or credential is accepted.

## At-most-once dispatch

All commands on a PR serialize. Before dispatch, a durable GitHub Actions bot
receipt records operation+PR+SHA. Repeated comments and reruns stop without dispatch.
On a timeout/uncertain POST or receipt update failure the claim remains; there
is no automatic retry. Inspect Actions before operator recovery. Delivery is
at-most-once, not guaranteed. Keep receipt comments for this guarantee; do not
delete a claim to force another request without resolving the prior outcome.

Accepted dispatch is not successful execution. The main-chat coordinator must
read the actual guarded run, verify exact candidate SHA, fixed inputs and final
conclusion, then return its URL. Do not infer attribution from the latest run.
The receipt links the dispatcher run, not an invented child run ID. If the API
cannot establish attribution, report unconfirmed. A failed check blocks progress.

## Activation and evidence

The `issue_comment` workflow must be on default `main` to run. Preparing a PR does not
activate anything; do not run the feature-branch workflow as a shortcut.
Offline validation: `python -m unittest discover -s tools/tests -v`.

Required final evidence: real phone-originated main-chat request, that chat's
GitHub task comment, executor commit, CI on the exact commit, readback by the
main chat, its command comment, attributed successful guarded preflight. A
Mac-authored setup commit/dispatch is not that chain. If main-chat GitHub tools
are unavailable, fix that blocker rather than manually relaying tasks.
If the owner chooses the existing cloud continuation as the final coordinator,
preserve the original history and do not create more conversations.

## Observed bootstrap on 2026-11-09

Main chat created [probe PR375](https://github.com/bimoool/pullup-trainer-bot/pull/375)
from main476d8e7. Preparation commit849294138a002cf81500d2492b6508f7c3035c07
contains only a pending documentation receipt. Its
[task comment](https://github.com/bimoool/pullup-trainer-bot/pull/375#issuecomment-6739084986)
was posted by the main chat. Codex
[replied](https://github.com/bimoool/pullup-trainer-bot/pull/375#issuecomment-6739087533)
that an environment must be created for this repository. No executor commit yet.
The main chat read this result back. Tests42610343922 and E2E42610343700 classified
the preparation change as docs-only: heavy jobs skipped, not full tests passed.

The bot's environment-settings link redirected to ChatGPT home in the owner's
Safari session. Current Settings > Code review recognizes this repository and
has reviews enabled; it offers no task-execution environment selector. Extra
review credits are off and were not changed. The already published environment
for ordinary cloud chats has not proved compatible with this GitHub task path.
This provider/environment mismatch is a blocker, not a successful smoke test.
The owner subsequently confirmed phone-to-primary-chat-to-GitHub readback.
The complete execution/preflight chain remains unverified. Coding already works
in the primary chat's cloud runtime; the optional legacy executor is not required
for that coding path. Release checklist and evidence live in issue #377.

Staging evidence is invalidated by any newer attempt through either staging
workflow, including failed, running and non-main dispatches. Both staging deploy
workflows and fixed release QA share the `deploy-staging` concurrency group.
Do not deploy staging through manual SSH during release validation: Actions cannot
attest changes made outside its deployment workflows; restart the guarded staging
and QA sequence after any such intervention.

## Read-only recovery observation

`/pullup staging-snapshot SHA` requests the fixed `staging-snapshot.yml` workflow
from trusted main. It invokes only the installed literal `./qa-staging.sh snapshot`
through the restricted staging key. It reads reserved synthetic profile summaries,
never provisions profiles or touches production. As with preflight, it remains
available after failed CI/deployments; owner/repository/current-PR-head guards and
durable claims still apply. The supplied SHA attributes the request; it is not a
claim about the running build or a successful prior provisioning transaction.
A failed/uncertain provision must be reconciled before any new state-changing QA.
A snapshot alone cannot prove which interrupted commands committed: combine it
with administrative execution receipts and active-process/lock evidence.
