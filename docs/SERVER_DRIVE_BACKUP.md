# Server-side encrypted PostgreSQL backup (draft, not installed)

The owner-authorized runner in `deploy/drive-backup.py` sends backups directly
from the existing VPS to the owner's existing Google Drive account. A systemd
timer runs daily at 03:30 UTC (up to 15 minutes jitter, persistent after reboot).
Neither a laptop nor this coding runtime participates in scheduled execution.
This PR does not install anything or authenticate to Drive. Keep it draft until
the current production recovery/release is resolved and the checks below pass.

## What VERIFIED means

The runner holds the **existing** production Actions, guarded deployment and
staging locks, in that order, through dump, encryption, upload and verification.
Missing locks or contention fail closed; it never replaces a lock inode. Use the
guarded entry points for deployment/rollback; an uncoordinated manual database
writer can still race any backup. PostgreSQL `pg_dump -Fc` takes a consistent
snapshot while app writes continue. No app/schema/workflow changes are made.

The dump streams through `age` into a root-only ciphertext file. Plaintext is
never written to disk. The VPS has only the approved **public** recipient;
the corresponding private decryption identity stays in the owner's recovery kit,
off the VPS and out of CI/cloud tools. The runner does not select another SSH key
or generate keys. An existing approved owner SSH recipient may be used explicitly
to preserve archive compatibility; the deployment key is not a substitute.

Before success, the runner reads Drive metadata (ID, folder, size, MD5, trashed)
and then **downloads the actual ciphertext on the VPS**, streaming SHA-256 and
byte count without retaining a second file. Both must match local ciphertext.
Metadata alone is insufficient. `VERIFIED` proves ciphertext transport integrity;
it does **not** prove decryption, restore compatibility, coverage of non-DB assets,
or an end-to-end recovery drill. It is not a production-release acceptance result.

The daily operation ID is `backup-YYYYMMDD` in UTC. A root-only fsync/atomic receipt
under `/root/backups/drive-operations/` is claimed before dumping. A Drive file ID
is allocated and durably recorded **before** upload. An existing receipt is never
automatically replayed: VERIFIED returns the same receipt; failed/unknown attempts
remain failed/unknown and nonzero. Interrupted RUNNING receipts are reported as
UNKNOWN. This avoids duplicate remote writes after a lost acknowledgement.
Changing folder/recipient refuses an existing operation binding.

Local ciphertext is removed after an ordinary completed attempt, including errors.
A power loss/SIGKILL can leave ciphertext and RUNNING or `.pending` receipt files.
They remain private evidence for owner review; no startup sweep or remote deletion
is performed. A pending receipt blocks an ambiguous claim rather than replaying it.
All remote retention is **report only**: no Drive file, existing archive or user
data is deleted, and no automatic retry loop or remote retention policy is enabled.

## Provisioning blockers (owner action, not performed by this PR)

1. An approved OAuth application/client and the owner's explicit offline grant
   are required. Request only `https://www.googleapis.com/auth/drive.file` with
   `access_type=offline` using an approved owner-side consent flow. A dedicated
   backup app is preferable to a grant shared with unrelated integrations.
   External apps left in **Testing** generally have seven-day refresh tokens;
   use an approved production-status app or an appropriate Workspace internal app
   before treating the timer as unattended. An API/client registration, publishing
   or verification step is not authorized or performed here.
2. The destination folder must be created/authorized by **the same OAuth app**.
   A folder made by the ChatGPT connector, another app or manually in Drive is
   not automatically visible under `drive.file`. The folder ID is a destination,
   not a security scope. No access to older archives is assumed. Do not broaden
   to full-Drive scope to work around a failed folder check without owner decision.
3. Provision the approved public encryption recipient and retain/test its private
   identity in the owner's recovery kit. No key, token or recipient is generated
   by this work. Never copy a private identity to the VPS.
4. Test revoked/expired auth, transfer errors, actual ciphertext readback and an
   owner-controlled isolated restore drill. Recover with a compatible PostgreSQL
   tool version and the required roles/extensions; this feature dumps one DB,
   not PostgreSQL global roles, Docker images, `.env`, uploads or host settings.

The remaining whole-project recovery inventory is explicit: approved source
commit/repository access and dependencies; application `.env`/secrets and external
service credentials; host/Compose/nginx/systemd/SSH configuration; PostgreSQL
roles/extensions; any uploads/assets outside PostgreSQL; encryption identity and
passphrase; Drive/OAuth account access, MFA and recovery codes. These items are
**not covered or verified by this DB-only utility**. Keep the sensitive recovery
kit in owner-controlled storage, separately reviewed. Do not infer full-project
recoverability from a VERIFIED DB ciphertext or add an unreviewed companion bundle.

Connected Google Drive credentials belong to the connector. Do **not** export,
extract or reuse them. No connector credential, production dump or plaintext
recovery content may enter this runtime, GitHub, CI logs or artifacts.

## Fixed private configuration

Only these three files are accepted, all root-owned mode **0600**, under
root-owned `/etc/pullup-drive-backup` mode **0700**, with no symlinks:

| File | Content |
| --- | --- |
| `config.json` | JSON object with exactly `folder_id` (Google Drive folder ID). |
| `oauth.json` | JSON object with exactly `client_id`, `client_secret`, `refresh_token`, each a nonempty string. An approved existing OAuth client is required. |
| `recipient.txt` | One public age `age1…` recipient, or explicitly approved owner `ssh-ed25519 …` / `ssh-rsa …` public key. |

No arbitrary token URL, command, executable, shell fragment, credential environment
variable or user-provided HTTP URL is accepted. OAuth refresh is in memory against
`https://oauth2.googleapis.com/token`. Drive operations use fixed HTTPS Google API
origins without redirects. The code cannot prove the original consent scope from
the secret file: provisioning must enforce the narrow grant. Tokens are not logged,
written to receipts or passed as subprocess arguments. Failure requires explicit
owner intervention; there is no browser consent or token-generation fallback.

## Installation after review and explicit owner authorization

This is a reviewable procedure, **not** an executed installation. Use an approved
checked-out SHA after current recovery is complete. Prerequisites on the existing
VPS: Python 3.12+, `age`, Docker Compose, existing guarded lock files, and GNU
`timeout`, `pg_dump` and `psql` inside the existing PostgreSQL 16 `db` container.
The fixed working directory is `/root/pullup-trainer-bot`; no Compose `-p`, new
host, container, API subscription or paid service is added. Missing prerequisites
block execution. Confirm adequate Drive quota and local ciphertext space as part
of owner acceptance; this utility adds no restore/resource-gate policy.

After the owner securely provisions the files above, install reviewed code/units
as root, without copying secrets into a shell command/history:

```sh
install -d -m 0700 /root/backups/drive-operations
install -m 0700 deploy/drive-backup.py /root/bin/drive-backup.py
install -m 0644 deploy/systemd/pullup-drive-backup.service /etc/systemd/system/
install -m 0644 deploy/systemd/pullup-drive-backup.timer /etc/systemd/system/
systemctl daemon-reload
```

Keep the timer disabled until an explicit owner-authorized manual run and
recovery check succeed. `systemctl start pullup-drive-backup.service` performs a
**real production dump and remote write**; do not run it as a coding check.
Inspect the corresponding private receipt locally on the VPS. After successful
acceptance, the owner can enable `systemctl enable --now pullup-drive-backup.timer`.
Check `systemctl list-timers pullup-drive-backup.timer` and `systemctl --failed`.
The unit suppresses stdout/stderr; it fails on non-VERIFIED results. Receipts,
not a quiet journal or an installed timer, are the evidence of success.

## Failure handling and recovery

The runner deadline is 1100 seconds; systemd bounds start to 20 minutes and allows
650 seconds for shutdown cleanup. Dump execution has a container-side hard limit
of 600 seconds and a 30-second lock wait. Failed dump/encryption attempts kill
local child groups and terminate only the random per-invocation PostgreSQL
`application_name`, then confirm absence. If that cannot be confirmed, the runner
holds locks until the container timeout horizon and records cleanup unconfirmed.
The systemd stop allowance preserves this cleanup window. SIGKILL/power loss can
only be reported as UNKNOWN; consult the private receipt and database state.

`AUTH_REQUIRED` requires fixing/re-authorizing the owner grant outside the runner.
`BUSY`, missing/unsafe credentials or missing locks are BLOCKED; no dump/upload
should be inferred. Upload uncertainty is UNKNOWN with the allocated remote ID;
verification failure is FAILED even if a remote file exists. Review that exact ID
on the owner's Drive before any separately authorized new attempt. Never delete
the receipt to retry the same operation. A different valid operation date is an
explicit new attempt; do not invent a successful receipt for a missed day.

Disable future runs with `systemctl disable --now pullup-drive-backup.timer`.
Stopping an in-flight service requires its cleanup allowance. Keep receipts and
remote backups; uninstall does not delete them or alter deployment controls.

For owner-side recovery: select a VERIFIED receipt, download that exact ciphertext
from Drive into an owner-controlled recovery environment, compare SHA-256 and size,
decrypt with the retained identity, inspect `pg_restore --list`, restore into an
isolated synthetic/recovery database, and validate application invariants before
considering production recovery. Never perform that plaintext drill in cloud/CI.
The receipt's ciphertext hashes are useful integrity evidence, not a signed trust
anchor: keep the recovery kit and independent verification under owner control.

## Offline evidence and remaining acceptance

Tests in `tests/test_scripts/test_drive_backup.py` use synthetic bytes, fake
Drive transport and temporary private files. They cover content corruption even
when metadata matches, idempotency, ambiguous transfer, interrupted receipt,
partial dump cleanup, private file permissions/symlinks, shared lock contention,
and safe error reporting. The focused suite passed **21 tests**. The changed-content
test was also run with download comparison temporarily removed: it failed because
the corrupted object was incorrectly VERIFIED, then passed with comparison restored.
No provider success is claimed by those tests.

The opt-in `test_drive_backup_real.py` passed **1 real synthetic drill** using only
the existing local test PostgreSQL 16 container: create two disposable databases,
dump through the actual runner pipeline, encrypt with age 1.2.1 and a disposable
test identity, decrypt only synthetic bytes, inspect/restore the archive and compare
exact rows. Both new databases and the test identity/recipient/ciphertext were
removed. Enable only in that isolated test environment with
`PULLUP_BACKUP_INTEGRATION=1 AGE_TEST_BIN_DIR=<unpacked-age-directory>`; ordinary CI
skips it when the explicit opt-in is absent. No production identity was created.

`ruff check app/ tests/ scripts/ deploy/drive-backup.py` and formatting of the changed
Python files passed. Offline `systemd-analyze --user verify` passed using a temporary
Docker dependency stub because the sandbox has no system-manager Docker unit;
this verifies unit syntax only, not installation or root-system integration.

Owner provisioning, live VPS command compatibility, actual Drive upload/readback,
timer installation and independent decryption/restore remain **unverified blockers**.
Do not merge/release this feature while the current production recovery is open.
