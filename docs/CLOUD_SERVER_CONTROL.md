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
`prod-control readiness|prepare|restore|receipt|adopt-runner <sha> ops-<id>` after
the continuity bootstrap below. Its four original
production/rollback command patterns remain unchanged. The root helper never
executes candidate app code, migrates or starts a bot. The fixed runner adoption
operation below replaces only the production runner.

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

## Continuity upgrade: runner adoption and R1 admission (2026-11-15)

**Implemented candidate; this continuity upgrade is not installed.** The observed
installed production runner is still SHA256
`7a1d42c1653fc443095b28809b888f110a3110b875eed58ecd5affc4f70d0dde`;
merging code does not replace `/root/bin` tools. The reviewed product runner and
rehearsal pin are unchanged by this controller change.

One existing administrative executor must first use the no-key installer from
the exact reviewed, merged controller SHA: `--check`, review its anonymous hashes,
then `--install`. The existing recipe above uses already fetched Git objects.
This is one administrative bootstrap job, not a command available through the
restricted production key. It cannot be performed from cloud chat without an
actual administrative executor. No new credentials, keys, services or general
shell command are introduced. The installer recognizes only the original policy
(for backward compatible initial bootstrap) or the observed installed pair:
dispatcher `3c48db20eddebb420d7933daca1b9a982128316d5ed041613ff7ead1f4033c42`
and helper `0e90e704cb69332eb1f9eb39ac98da5c2c13ed52630fa05db38a948d69161c6c`.
The upgrade preserves the original `before-cloud-control` backup and saves
separate `before-continuity` dispatcher/helper copies. Keys and both runners keep
their bytes and inodes; the installer updates only helper and dispatcher under
the existing production, guarded and staging locks. Unknown states require
administrative review and are not overwritten.

After bootstrap, the owner can use these exact new commands on the relevant
same-repository `codex/` PR, whose current head must equal the supplied full SHA:

```text
/pullup server-adopt-runner <40-hex-sha>
/pullup rollback-r1-apply <40-hex-failed-sha> /root/backups/prod-pre-<sha7>-<YYYYMMDDTHHMMSSZ>.manifest ROLLBACK-R1-prod-<sha7>-<same-timestamp>-<server-run-id> <failed-GitHub-run-id> <R1-check-GitHub-run-id>
```

Runner adoption requires current full CI/rehearsal, exact main-tree equality and
an original unedited owner command. Both dispatcher and child check admission;
the child also verifies trusted main workflow/actors and first attempts. Prepare
the candidate object first with the existing `server-prepare` operation. Server
adoption accepts no path/hash/URL argument. It fetches only the fixed origin main
ref, proves candidate-tree equality, reads only `deploy/deploy-production-guarded-run.sh`
from the already present candidate, checks Bash syntax without execution, and
atomically replaces only the installed production runner. It requires private
root-owned regular files, a known initial or last durably adopted old hash
(exact new bytes are idempotent), all existing nonblocking locks and no active
deploy/rollback/dump/restore. Old bytes and an exclusive operation claim are
persisted before replacement; helper, dispatcher, rollback and authorized keys
must retain both bytes and inodes. Services, checkout and application data are
not changed. Query the same operation with `server-receipt`; never replay a
changing command. A failed/interrupted adoption reports mutation uncertainty;
a pending durable adoption state refuses subsequent adoptions until reviewed.

R1 uses the existing production rollback workflow/environment/concurrency and
forced command. It does not require failed-candidate CI or equality to latest
main. It requires the original release PR's current head, an original unedited
owner comment, first-attempt bot-dispatched trusted-main failed apply and later
successful matching R1 check, exact latest jobs, manifest timestamp inside the
failed job and matching candidate/token. Both evidence workflow SHAs must belong
to main history. Another potentially changing production attempt invalidates
evidence; a later matching check supersedes an earlier check. Repository-wide
incident and execution claims are keyed by failed run, so another PR/comment,
manual workflow dispatch, a rerun or an uncertain API response cannot replay it.
The child persists its execution reservation before SSH. New checks expose kind,
mode and manifest in their run name; old unattributed checks cannot admit this
route; request a fresh read-only `/pullup rollback-check <sha> R1 <manifest>`
after activation. Read-only rollback-check claims bind kind, exact manifest and
owner request comment ID in addition to PR/SHA. A later owner comment may refresh
the same R1 check or request another kind/manifest; a rerun of an already reserved
comment deduplicates. Historical v1 claims remain preserved and do not prevent
new checks. Dispatcher reruns are refused, including events with only a historical
v1 claim; use a new owner comment for another read-only check. This does not
change incident-wide apply/execution claims or the
existing pinned incident-only R3 route.

R1 admission is not proof of recoverability or recovery. Installed server guards
still require the unchanged schema revision and no started backfill, restore
only prior application images, and never overwrite the database. Creating,
reviewing or merging this change does not authorize any production operation.

## Complete controller bundles (#406)

**Implementation candidate; not installed and not accepted from the cloud.**
Finish the frozen release before merging this follow-up: advancing main still
invalidates its exact-tree release gate. No existing release gate is relaxed.

The reviewed one-time conversion installs a small stable supervisor outside
replaceable bundles. The existing authorized-key forced command path stays
`/root/bin/prod-guarded-dispatch.sh`; only its contents become the fixed
`control-plane-entrypoint.sh` launcher. No key, SSH configuration, account,
package or general shell endpoint is introduced. Existing reviewed backup unit
definitions are installed disabled, with activation a separate owner decision.

Each immutable `/root/bin/control-plane/releases/<sha>/` contains exactly the
reviewed dispatcher, helper, production runner, rollback runner and a generated
hash manifest. The sole optional artifact is fixed `deploy/drive-backup.py`;
absence means backup capability unavailable. Optional files receive the same
Git-mode, size, syntax, ownership and hash guards; no arbitrary manifest paths
are accepted. Dispatcher/helper resolve their own bundle directory. One private
fsynced `active.json` switches the entire bundle; an invocation resolves it once
while holding the existing Actions lock and passes that open lock to the bundled
dispatcher. Existing production, guarded and staging locks/inodes remain in use.
Receipt reads bypass mutation locks. Independent runner adoption refuses inside
a versioned bundle; future controller and runner changes use complete adoption.

`/root/bin/control-plane-backup.py` is a separate stable, local-root-only scheduled
entrypoint. It rejects arguments and any SSH environment, reads one activation,
validates that complete bundle and executes only its fixed backup artifact using
isolated Python and a clean environment. It never selects the legacy root-bin
backup script. Immutable releases are retained, so a concurrent activation cannot
mix versions; the unchanged backup runner acquires its original locks itself.
SSH gains no backup command or flags. Reviewed backup code updates subsequently
use `server-adopt-controller`; return and explicit new-operation re-adoption of
the same immutable SHA remain supported.

Owner commands, in the original eligible PR conversation:

```text
/pullup server-adopt-controller <exact-current-pr-head-sha>
/pullup server-controller-status <adopted-sha> ops-<adoption-comment-id>
/pullup server-recover-controller <adopted-sha> ops-<adoption-comment-id>
```

Status may also query `ops-<recovery-comment-id>`. Adoption requires the original
unedited owner request, live PR/head binding, all seven existing exact-SHA
CI/rehearsal contexts plus attributed `authorization`, current main-tree equality,
trusted-main first-attempt dispatcher/child provenance, and a durable execution
claim before SSH. The server independently fetches only fixed origin/main and
checks exact tree and regular Git blob modes. No source URL, shell, path, hash or
arbitrary manifest is accepted from the caller.

The stable supervisor implements its own status and recovery. Their standalone
`controller-recovery.yml`/client path does not import the ordinary dispatcher;
broken bundled helper/dispatcher code cannot disable recovery. Recovery binds an
original adoption owner comment and private operation journal, validates its
saved previous local bundle, and refuses unrelated activation changes. It does
not require latest product CI, latest main-tree equality, or an unchanged source
PR head. It never fetches, reruns adoption, changes app images, starts services
or restores a database. Each new recovery comment has a separate durable claim.
An interrupted recovery that already switched is reconciled without switching
again. Uncertain transport is UNKNOWN: query the same operation; never replay.

Claims publish complete fsynced temporary records with atomic no-replace links;
partly written final claims are impossible. The prior activation is included
before staging, and the proposed activation is journaled before switching.
Incomplete staged directories are never executable. Activation and receipts
use file fsync, atomic replacement and directory fsync. Referenced releases and
journals are retained; this implementation performs no automatic garbage collection.

### Exact additional administrative bootstrap

Only after reviewed integration/full gates and current-release completion, the
existing authorized administrator fetches the exact reviewed merged SHA and uses:

```text
git show <reviewed-sha>:deploy/install-control-plane.py | python3 - <reviewed-sha> --check
git show <reviewed-sha>:deploy/install-control-plane.py | python3 - <reviewed-sha> --install
```

The installer requires fresh local origin/main tree equality and the recorded
PR404 helper/dispatcher pair plus the post-NEWLIVE production runner `e0773bd7…`
and the known installed rollback baseline. Unknown files/modes/symlinks refuse. It writes only
the new supervisor, complete initial bundle/activation, private controller ledger,
nonoverwriting `control-plane.bootstrap-before` copies, and finally the launcher.
It also installs the stable local backup launcher and the two exact reviewed
systemd unit files. It refuses unknown units/launchers, enabled or active units,
and unexpected loaded unit fragments before changing files. Known disabled units
also require empty loaded `DropInPaths` and no applicable exact-unit, hyphen-prefix
or global-type drop-in directories in standard systemd load locations, including
unloaded/runtime overrides and symlinks. Unknown overrides are refused, never
removed or modified by bootstrap. Known disabled units
retain their inodes. Systemd calls only inspect state: no daemon reload, enable,
start, authentication, package installation or backup runs occur in bootstrap.
Actual activation requires the separate provisioning/recovery evidence in
`SERVER_DRIVE_BACKUP.md`; installed disabled units are not working automation.
The production runner must equal already installed bytes. Installed rollback
`6286544a…` is accepted only as the preserved bootstrap baseline; the initial
active bundle selects the reviewed rollback source and records its computed
hash. The combined candidate includes PR412's atomic database-swap repair and
PR413's current admission/manual-reservation controls. No installed rollback
file is overwritten and no database operation is performed during bootstrap.

The expected production guard is the exact reviewed PR417 `5014be8` source,
SHA256 `e0773bd7d23020add0fb84f970a9fa887c9d458b5ba5d0940c04fb906a7821ee`.
The currently installed `986…`, earlier `785…` diagnostic guard and old `c97…`
are refused;
bootstrap cannot replace them with its source or accept them as another known
version. Source equality and a guard hash are not primary runtime acceptance:
the coordinator must first verify primary NEWLIVE and the corresponding guard
receipt, then all combined gates/reviews. Prepared job `6897648541` remains
NOT STARTED with its window CLOSED until those prerequisites and the exact
combined source head are pinned. No OAuth or disaster-recovery readiness is
implied by this source candidate, installation plan, or backup transport code.
Legacy helpers/runners retain bytes and inodes; authorized_keys, existing backups,
locks, production checkout, services and data remain unchanged. Known interrupted
bootstrap states can resume; unknown activation or supervisor bytes refuse.

Acceptance requires synthetic SIGKILL coverage around claim/staging/activation,
recovery and launcher publication; provenance/dedup/source/lock refusal tests;
independent security review and full CI; then an actual cloud adoption, status
and explicitly requested return of a harmless reviewed bundle. Broken-bundle
injection is confined to synthetic fixtures. Record exact source/hashes and run
URLs. Installation or a green dispatch alone is not end-to-end acceptance.
OS/SSH failure, damaged trusted storage, or a defect in the small stable trust
anchor can still require an administrator from a trusted device.

### Fixed R3 delivery recovery after pre-SSH refusal (#409)

The original child run 43724053051/job 132841996080 failed the incident admission
step and skipped SSH. The public metadata reconstructs valid guards; its historical
HTTP/guard cause is **UNKNOWN**, because the old client discarded those details.
This capability does not claim to repair that historical provider failure.

This first delivery capability was consumed by owner comment 6896948857 and
its durable claim. The command is retained here for audit; do not repost/rerun it:


```text
/pullup incident-r3-recover e9f32dd194aab140f63c445e0c2d2eddf59b2b91 ROLLBACK-R3-prod-e9f32dd-20261115T075403Z-247039 6895994270 43724033626 43724053051
```

This is the same original incident, candidate, approval, manifest and token.
It never reruns the old child, selects another manifest or allocates a new server
operation. A new owner comment and trusted-main first-attempt dispatcher/child
must preserve the original approval and dispatch claim. The dispatcher and child
freshly check both exact original deploy/check run+job pairs, original dispatcher,
and original latest failed first-attempt child/job. The exact known job topology
must show admission failed and SSH skipped; pending, changed or unknown evidence
refuses. A dedicated recovery dispatch claim persists before dispatch and blocks
another delivery, including another comment. The child requires that claim's
binding and persists the **same global incident execution marker** before SSH.
Production workflow concurrency serializes execution admission. Both original
and recovery claims remain permanently preserved. A late original path is refused
once recovery is claimed. No automatic retries, deleting claims or bypassing
manual child dispatch are supported.

Any ambiguous claim/dispatch/SSH response requires reconciliation of the existing
claims and run. Once execution is reserved, no recovery route may replay it even
if SSH never starts. Existing server flock locks and guarded manifest/token checks
are unchanged; they do not constitute a new durable server dedup ledger. This
change adds at-most-once **cloud** execution admission, without changing the R3
runner or asserting that recovery completed. Failure diagnostics contain only
allowlisted stage/guard/failure codes, numeric HTTP status or null, and
`RECONCILE_NO_REPLAY`; no URL, body, token or exception detail is printed.

### Execution claim permission and manual exclusion

Recovery child 43730752868/job 132862408612 ended at admission before SSH, with
`failure=HTTP`, `http_status=403`, `stage=CLAIM_WRITE`, and no global execution
claim. Its owner request is 6896948857 and dispatcher 43730724401. The body/reason
of that 403 was not retained, so its precise cause remains **UNKNOWN**. The older
43724053051 failure's cause also remains UNKNOWN.

The rollback workflow now explicitly grants `pull-requests: write`, matching the
working comment-writing dispatcher/server-control workflows. GitHub documents
[create issue comment](https://docs.github.com/en/rest/issues/comments#create-an-issue-comment)
as accepting Issues(write) or Pull requests(write). Aligning the explicit PR
permission is a compatibility correction; it does not prove the historical 403's
cause. No content/action permission is broadened. A future 403 diagnostic may
emit only an allowlisted exact message enum and bounded numeric remaining/limit/
reset/retry-after values. Unknown, malformed or oversized messages stay UNKNOWN;
no response body, URL, token, arbitrary header or exception detail is printed.

Both old incident admissions also recognize this exact owner-authored reservation
on PR #399, **only after a separate owner decision to reserve manual execution**:

```text
<!-- pullup-incident-r3-manual-execution-reserved-v1:43691971076 -->
MANUAL R3 EXECUTION RESERVED e9f32dd194aab140f63c445e0c2d2eddf59b2b91 6895994270 ROLLBACK-R3-prod-e9f32dd-20261115T075403Z-247039
```

The full body must match exactly, and the live author identity/OWNER association
and PR binding must match the repository owner. It denies cloud admission before
new dispatch/execution reservations. Preserve this comment permanently, including
after manual execution; do not edit or delete it. A marker alone, proposal prose,
quoted proposal or another author cannot reserve execution. Publishing this code
or proposal does not post a reservation and does not authorize a manual action.
This exclusion coordinates the separately controlled manual route; GitHub comments
cannot atomically lock out an already admitted/in-flight SSH operation. Before
manual reservation/action, reconcile the current runs and execution claims and
prove no cloud execution is active. The existing server locks remain required.

Both prior dispatch claims are retained. The fixed second-delivery capability
below supplies a separate reviewed admission without replaying either exhausted
route. Never delete claims, rerun a failed child or substitute a new manifest/incident.

### Second and final fixed failed-before-SSH delivery

After independent/native review, mandatory checks and trusted-main integration,
a separate owner approval on PR #399 may use this exact unedited command:

```text
/pullup incident-r3-redeliver e9f32dd194aab140f63c445e0c2d2eddf59b2b91 ROLLBACK-R3-prod-e9f32dd-20261115T075403Z-247039 6895994270 6896948857 43730724401 43730752868
```

This capability is fixed to original owner approval 6895994270 and the first
recovery approval 6896948857/dispatcher 43730724401/failed child 43730752868/job
132862408612 at trusted head f6bf15dafa03dd1aa74c4353d7099a8b3563c9e7. It uses
existing structured GitHub metadata only; the recorded HTTP403 is descriptive,
not a privilege/admission assertion. Both old child run/job identities and latest
first attempts must remain terminal failures with the exact known step topology:
admission failed, SSH skipped. All original deploy/check evidence, immutable
owner comments, owner/bot actor and triggering-actor identities, trusted heads,
and both original dispatch claims must remain unchanged and uniquely bound.

A new original owner comment and first-attempt trusted-main dispatcher reserve
one dedicated `pullup-incident-r3-redelivery-v1:43730752868` claim before dispatch.
The new first-attempt bot child binds that claim to the new approval/dispatcher,
refreshes the entire fixed evidence/approval/claim chain and both execution
exclusions immediately before reserving the **same** global incident execution
marker under production concurrency. Both older paths deny a redelivery claim.
A global execution reservation or explicit owner manual reservation denies all
three paths. Unknown, pending, changed, duplicate or ambiguous evidence refuses;
uncertain POST/dispatch/SSH outcomes require reconciliation and never replay.
There is no generic retry, caller-selected incident, new server operation,
manifest/token change, automatic retry or third delivery capability. Existing
forced SSH command, server locks and rollback runner remain unchanged. Publishing
or integrating this capability does not approve or perform recovery.
