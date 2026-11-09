# One-chat GitHub coordination: prepared, not operational

The coordinator stays in the main chat. GitHub holds service task briefs, PRs,
executor commits and CI receipts. A GitHub Codex reaction is not completion.
Do not enable API-backed `codex-task.yml propose`, extra credits or the old
`develop/current` queue. Server keys remain in GitHub Secrets.

## Fixed read-only server command

After review and owner-authorized merge to the trusted default branch, the owner
or the owner's authorized GitHub connection in the main chat can post exactly:

```
/pullup staging-preflight <40-character-lowercase-current-PR-head-SHA>
```

Only an open same-repository `codex/` PR targeting `main` is eligible. PR372 and
PR374 are excluded from this setup adapter. Extra arguments, shell syntax,
production, deployment, migration and QA provisioning are unsupported.
The only dispatch is existing `deploy-staging-guarded.yml` from trusted `main`,
with `converge=preflight`, `start=no`, `users=-`. The adapter receives no server
key or runtime PAT. The existing guarded workflow keeps its forced-command SSH.

The adapter validates repository name/ID, owner ID/login, sender, association,
live comment, current PR head, base/head repository and active workflow. It
checks out only `github.workflow_sha` from trusted `main`, never PR code.
Commands are read as JSON, never evaluated by a shell. No user-supplied URL,
workflow filename or credential is accepted.

## At-most-once dispatch

All commands on a PR serialize. Before dispatch, a durable GitHub Actions bot
receipt records PR+SHA. Repeated comments and reruns stop without dispatch.
On a timeout/uncertain POST or receipt update failure the claim remains; there
is no automatic retry. Inspect Actions before operator recovery. Delivery is
at-most-once, not guaranteed. Keep receipt comments for this guarantee; do not
delete a claim to force another request without resolving the prior outcome.

Accepted dispatch is not successful preflight. The main-chat coordinator must
read the actual guarded run, verify exact candidate SHA, fixed inputs and final
conclusion, then return its URL. Do not infer attribution from the latest run.
The receipt links the dispatcher run, not an invented child run ID. If the API
cannot establish attribution, report unconfirmed. A failed check blocks progress.

## Activation and evidence

The `issue_comment` workflow must be on default `main` to run. This PR does not
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
Mobile availability and the complete phone-to-preflight chain remain unverified.
