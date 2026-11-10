# Crimpd black-box audit — 2026-11-10

Status: **BLOCKED before UI execution**. This is a new bounded pass, not a
revalidation of historical DONE rows. No product code or deployment changes.

## Scope and evidence rules

Crimpd is the UX reference, not the source of the project's progression formulas.
OBSERVED means a fact actually checked in this pass; INFERRED means a conclusion
with its stated basis; UNKNOWN means unexecuted/unavailable behavior. Historical
secondhand observations retain their historical meaning and are not promoted.

Read: AGENTS.md, CLAUDE.md, product-reference and crimpd-reference skills,
CRIMPD_FULL_PARITY_8_5.md, FUNCTIONAL_AUDIT_WAVE_1.md, and wave1/A-reference
COVERAGE.md / GOLDEN_TRACES.md. All requested files exist. The prior reference
lab and its recipe/ledger also exist. The old recipe's initial 8.4.0 installation
instructions are historical; no installation/reset instructions were executed.

Repository baseline: `7c89ce622749608fc4c9c27daa0062272f3efccb` (origin/main at
start). Prior pushed work on codex/cloud-command-dispatch-20261109 was clean and
preserved; this report uses a separate branch.

## Observed environment

| ID | Initial state and steps | Observed result | Evidence |
| --- | --- | --- | --- |
| ENV-1 | Inspect installed tools and list existing AVDs/device connections | Existing ref_pixel6, ref_pixel6_play and test_pixel6_play; no connected emulator initially | Sanitized tool inventory; no account/token inspection |
| ENV-2 | Start existing ref_pixel6_play, without wipe-data/install/data reset | emulator-5554 becomes available; existing userdata retained | ADB devices reports a connected Android virtual device; vendor emulator37.1.11.0 |
| ENV-3 | Read only package metadata of com.crimpd.ui | **Crimpd8.5.3, versionCode8050300, installer com.android.vending** | Package-manager version/installer fields only; no APK extraction or decompilation |
| ENV-4 | Ask computer-use tool for the running emulator executable and process name | Both attempts return **Invalid app** | getApp(executable path); getApp(qemu-system-aarch64) |

The emulator reported unavailable host DNS resolution at startup. Whether that
blocks Crimpd itself is **UNKNOWN**: no app screen/network behavior was observed.
No DNS/host security settings were changed. No new environment, account, token,
subscription or acceptance of terms. No application data was cleared.

Available UI automation cannot select the emulator window. Installed ADB is
available, but explicit permission to use ADB for UI actions was requested and
has not yet been received at this checkpoint. No ADB input, UI dump, app launch,
screenshot or UI scenario has been executed in this pass.

## Reproducible bounded scenarios, in priority order

Every case below is **UNKNOWN / NOT RUN** in this pass. Version baseline is
8.5.3(8050300); recheck it after execution. These are steps to perform, not
asserted Crimpd behavior. Use only new objects named `REF TEST - 20261110 - <ID>`.
Leave other workouts, plans, account data and historical logs unchanged. Capture
only screens containing synthetic objects or public catalogue content; never
publish raw UI dumps or unrelated history.

| Case / old evidence gap | Initial state | Steps | Result/evidence needed |
| --- | --- | --- | --- |
| C01 / R-J2 R2,R4; E12 | Existing signed-in session; no new object from this pass | Home create-workout; inspect each wizard step; try progressing without exercises; search a unique synthetic exercise; inspect Create Exercise form without accepting new terms | Step order, exact validation, fields, save/cancel semantics; synthetic-only evidence |
| C02 / R-J2 R6 | New synthetic workout draft | Configure minimal supported timed/repetition exercise; save; reopen by exact synthetic name; edit name/protocol; save and reopen | Actual landing screen and persistence; no inferred Save behavior |
| C03 / R-J3 R1,R4 | Public catalogue workout, never added to a plan by this pass | Catalogue/category/search → detail → inspect load/timer → start → pause/resume → complete or cancel | Full route, prompts, phase transitions and whether a plan is required |
| C04 / R-J7/J8 R2,R3; N5 | New synthetic session in work/rest, record displayed timer and monotonic elapsed time | Pause → background → wait bounded interval → return; then repeat unpaused | Separate paused/unpaused timer behavior; retained inputs; no implementation inference from countdown alone |
| C05 / R-J1 R11 | Synthetic session reaching review | Dismiss review without Save; inspect only the synthetic log's presence; reopen app | Whether dismissal saves/discards/asks confirmation; duplicate prevention UNKNOWN until tested |
| C06 / R-J1 R12; R-J5 R3 | Synthetic completed session explicitly saved | Journal → synthetic entry → reopen details → inspect Edit/Clone forms → cancel or save only own entry → reopen app and entry | Actual stored facts, available fields, date defaults and persistence |
| C07 / R-J4 R1,R7,R8; E10 | Existing Plans, unrelated plans untouched | Create uniquely named synthetic blank plan if available without purchase; inspect zero-workout week and CTA | Exact empty-state wording, validation, actionable next step; stop at paywall |
| C08 / R-J2 R8,R9; R-J4 R3–R5 | Synthetic workout and synthetic plan | Add to Plan → all sheets/day/week selectors → current/future week → Schedule → move only synthetic row → reopen → start that row → cancel | Day/week semantics, current-week marking, row-to-player route and persistence |
| C09 / R-J1 R5,R6 | Public skill-template detail | Inspect Add flow; if free and it creates only a uniquely named synthetic plan, continue and inspect resulting list/week | Template start-date/name prompts and resulting state; stop at paywall/terms |
| C10 / R-J1 R7; R-J3 R5 | Synthetic scheduled row and same synthetic workout | Complete/save from plan, inspect counter; if safe, start same workout from catalogue and compare | Actual plan-credit behavior; do not infer credit merely from presence of counters |

Fresh-install/account-creation observations, subscription purchase/expiry changes,
deletion of another person's history, account deletion and accepting new terms
are excluded. Clean-account empty states remain UNKNOWN under this task's
no-reset/no-new-account restriction. Plan deletion is unnecessary for the first
bounded pass; do not delete retained synthetic evidence automatically.

## Differences and limitations

No new Crimpd-versus-product behavioral difference is established yet: UI
execution is blocked and the product was not changed or re-audited. Existing
matrix DONE rows about our implementation are not fresh reference evidence.
In particular, background timer/reopen reconciliation, final-10-second cues,
automatic log-panel expansion, Schedule semantics and Edit/Clone forms must not
be described as newly observed until the corresponding cases run.

Synthetic-object ledger for this pass: **none created** at this checkpoint.
No continuous monitoring has been configured.

Next concrete step: obtain permission for the existing ADB UI-control path,
then inspect the current app state and run C01–C08 as access/gating permits.
If the emulator disconnects or a login/license/paywall/terms gate appears, record
the exact blocker and stop that branch without reinstalling or clearing data.
