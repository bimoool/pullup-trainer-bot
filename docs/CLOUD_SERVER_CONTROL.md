# Cloud server control — reviewed bootstrap and acceptance

Status: implementation candidate; **not installed or accepted end-to-end**.
This is separate infrastructure work. Frozen product candidate remains
`d9506be696f5883936f321a68c842dae19a17a22`; this PR does not deploy it, merge
anything, run migrations, change formulas, create credentials or authorize apply.

## Remaining local dependencies and their replacements

| Dependency observed in #377 | Replacement | Actual state / owner decision |
| --- | --- | --- |
| Mac terminal + personal gh auth to send a server command | Main cloud chat posts the exact owner command through its existing GitHub connection. Trusted-main dispatcher uses GitHub Actions token and existing restricted production key | Existing bridge works historically; new commands require reviewed integration/install and a fresh main-runtime proof |
| Administrative SSH to discover revisions/images/resources/runner hashes | `server-readiness` returns only anonymous metadata and an operation receipt | Implemented here, not installed |
| Administrative fetch when preflight cannot find a candidate | `server-prepare`: exact checked PR SHA, fixed origin/repository, at most one fetch, no checkout/reset/app execution | Implemented here; object presence is checked after timeout before reporting uncertainty |
| Mac connection kept alive during a long recovery check | Detached bounded server worker + durable server receipt, then `server-receipt` from GitHub | Implemented here; interrupted/failed operation IDs never replay work |
| Manual backup/restore shell | `server-restore`, consistent server-side dump into private files; standalone PG16, no network/ports/live mounts, CPU/memory/tmpfs/time limits; no bot/app starts | Capacity gate currently refuses on production VPS: last observed477MiB available vs required784MiB. No recovery container/dump was started in authorized pass |
| Secret/key copying during setup | Existing GitHub Secrets, pinned public host fingerprint repository variable, one reviewed no-key-rotation installer | Keys stay unchanged. Fingerprint variable must be populated from already verified host key before activation |
| External encrypted recovery copy | Existing approved destination + access + explicit recovery receipt | Destination/access not established. No new storage/account/key/purchase or dump transfer is authorized by this PR |
| Browser QA from Mac | Existing fixed two-browser release QA through GitHub, reserved identities provisioned per browser | Existing successful run42861825241; no new run needed for current frozen candidate |
| Real Telegram/device acceptance | Real authorized client/device; owner may perform actual iPhone acceptance | Mac native short synthetic scenario passed after explicit7-day staging ADMIN_GRANT. This is not iPhone/B10x5 acceptance. Reserved browser identities are not native Telegram identities |
| One-time installation of a reviewed access extension | Existing administrator installs only the reviewed helper/dispatcher after checks/review; no new key or broad shell route | Bootstrap remains explicit. Future routine operations use GitHub only; do not claim the bootstrap itself proves the cloud chain |

## Fixed command surface

In an eligible codex/ PR conversation (never PR372/374):

```
/pullup server-readiness <exact-pr-head-sha>
/pullup server-prepare <exact-pr-head-sha>
/pullup server-restore <exact-pr-head-sha>
/pullup server-receipt <exact-pr-head-sha> ops-<original-comment-id>
```

Only repository owner comments with live owner/repository/PR/head verification
are admitted. Prepare/restore require the existing full exact-SHA CI/rehearsal
checks. The child rechecks comment/PR/SHA and trusted dispatcher-run provenance.
Workflow and adapter come from trusted default main, not PR checkout. No shell,
URL, database, path, profile ID, secret, script or runner mode is accepted as input.
Existing production/staging deploy/rollback gates are unchanged.

The existing restricted production key reaches literal
`prod-control readiness|prepare|restore|receipt <sha> ops-<id>`. Its four original
production/rollback command patterns remain unchanged. The root helper never
executes candidate app code, installs a runner, migrates or starts a bot.

## Receipts, serialization and failure handling

GitHub reserves a durable comment claim before dispatch. Each new owner request
has an operation ID derived from its comment ID; transport acceptance is not
success. The server exclusively creates `/root/backups/cloud-operations/ops-N.json`
and binds candidate/action. Reusing an ID returns its existing RUNNING/FAILED/
VERIFIED result; it never repeats a changing operation. Receipt reads remain
available while a detached worker holds locks. A new operation ID is an explicit
new request, not an automatic retry policy.

Operations hold existing production Actions → guarded → staging locks and refuse
other deploy/rollback/dump/restore processes. The dispatcher open-file description
is reused to avoid self-deadlock. Root/admin direct invocations still require the
operational invocation freeze: advisory locks cannot prevent an unrelated root
operator ignoring them. Existing lock files/inodes are not recreated by the helper.

On disconnect, request the **same** operation's receipt. Unknown state remains
unknown until reconciled. No claim deletion, blind fetch/restore replay or
production apply-as-discovery. GitHub receives operation ID, stage, outcome,
next step and strict allowlisted anonymous JSON only. SSH/private restore logs
and real data never become artifacts or chat content.

## Recovery isolation and resource gates

Before backup/restore: preserve400MiB available live reserve, allow256MiB for PG
and128MiB overhead (minimum784MiB), plus3GiB disk reserve and conservative
restored-data/WAL/temp/dump budgets. A low-resource result is BLOCKED, not success.
The standalone PG16 image is an existing exact image ID; it is not pulled or
upgraded. Network none, no published ports, read-only rootfs, no production mounts
or env file, user999, no capabilities/new privileges, no restart, one restore
worker, CPU0.5, memory/swap256MiB, bounded tmpfs and900s watchdog. Check image
major/UID before use. Cgroup-charged tmpfs can cause a controlled OOM; that is a
failed restore, never a reason to relax limits. Watch the live reserve during
startup/restore. Keep data private server-side and remove only this operation's
own labeled standalone container. Retain its protected backup/checksum/receipt.

The fresh pg_dump is consistent while writers run; it is **not** the final
stopped-writer rollback point. No live-row comparisons while writers run.
Verify restored Alembic, index/constraint validity and SQL readability internally.
No app starts against a real copy. External encrypted recovery remains a separate
owner-destination/access decision; checksum/presence is not restore proof.

## Bootstrap and exact installation scope

Require reviewed PR head, green Linux tests and independent review first. Existing
administrator fetches that reviewed control-tools SHA as metadata only. Run
`git show <reviewed-control-sha>:deploy/install-server-control.py | python3 - <reviewed-control-sha> --check`
then the authorized `--install` mode. No key-rotating installer.

Changes are limited to root-owned mode700 `/root/bin/server-control.py`, atomic
replacement of `/root/bin/prod-guarded-dispatch.sh`, and nonoverwriting preserved
`prod-guarded-dispatch.before-cloud-control.sh`. Initial dispatcher must have
verified baseline hash9313be214b5dc1ad7756171d80f649b3394e1d50a92140a3980933be156706e5;
unknown helpers/policies/symlinks are refused. Existing keys, deploy/rollback
runners, checkout, services and data remain untouched. Pin `VPS_HOST_KEY_SHA256`
to the already verified ed25519 host fingerprint using a repository variable;
the new workflow refuses missing/mismatched pins. This adds no credential.

Do not silently merge this infrastructure PR into frozen product scope.
Current production release gates require candidate/main tree equality: advancing
main with these files before releasing d9506be would invalidate that equality.
No guard was relaxed here. Sequence integration with the release coordinator;
if a different activation order is required, obtain an explicit reviewed policy
solution rather than weakening the frozen release gate or claiming completion.

## Required acceptance from the main cloud runtime

1. Record main chat runtime environment observation/access-check readiness;
   existing token ready, api.github.com enforced/available, exit0; no secret value.
2. From that runtime, owner GitHub connection posts server-readiness on an exact
   eligible PR head. Read dispatcher and actual child outcome/receipt.
3. From that runtime post server-prepare once. Confirm VERIFIED/object present/
   unchanged checkout in the real server receipt and actual workflow conclusion.
4. Query its same operation ID using server-receipt and read it back in the same
   main chat. Include exact command/claim/result/run URLs and runtime attribution.
5. Mac is not in this operation path. A local smoke, installed files, accepted
   dispatch or prepared token is insufficient. Until these steps actually run,
   transition status remains NOT VERIFIED. Device acceptance and unresolved
   recovery capacity/destination decisions remain separately visible.
