# Staging runbook: aged-state convergence (#301)

The owner approved this on 2026-10-06. It is the staging acceptance for the narrow self-heal of an active
inclusion whose snapshot has a **missing or empty** `program_items` (the owner's «Неделя 4 · 0 из 0»).

The fix is one canonical function, `PlanWeekService.converge_inclusion_snapshot`. The runtime calls it on
every `GET /plan`, and the targeted tool `scripts/repair_plan_convergence.py` calls the same code. Behaviour
and invariants are in `docs/PROJECT_SPEC.md` («Сходимость «старых» инклюзий»); the incident write-up is in
`docs/ENGINEERING_NOTES.md`.

## Order matters

The deployed runtime **heals the account by itself the first time anyone opens Планы** with it. To see the
dry-run and apply steps on the real account:

1. Take the BEFORE snapshot.
2. Deploy.
3. Run the dry-run **before** opening the Mini App with that account.

If the account was already opened on the new build, the dry-run correctly reports `"nothing to do"`. The
AFTER snapshot then still proves the result, but there is no dry-run evidence for it.

Every command below runs on the VPS, from the **staging** compose project, and is scoped to one `--telegram-id`.
Nothing here touches production.

## Steps

**0. BEFORE (read-only, already done once by the owner).**
```bash
docker compose -p pullup-staging exec app python scripts/qa_state_snapshot.py --telegram-id <OWNER_TG_ID> > before.json
```
Expected diagnoses: `CURRENT_WEEK_EMPTY`, `SNAPSHOT_NO_PROGRAM_ITEMS_KEY`, `LIVE_HAS_ITEMS_SNAPSHOT_DOES_NOT`,
`INCLUSION_NOT_IN_CURRENT_WEEK`.

**1. Deploy the fix to staging.** Use GitHub → Actions → «Deploy staging» → ref `claude/wonderful-tesla-2dph8h`
(or the branch it is merged into). Do **not** open the Mini App with the owner account yet.

**2. Dry run (the default; the transaction is rolled back and nothing is written).**
```bash
docker compose -p pullup-staging exec app python scripts/repair_plan_convergence.py --telegram-id <OWNER_TG_ID> > dry-run.json
```
Check the output (`dry-run.json`) for all of the following:
- `result` = `"dry-run: rolled back, nothing written"`.
- `guard_violations` = `[]`.
- `mutation.snapshot_repairs` has exactly one entry: the «Подтягивания» inclusion, with
  `reason: "missing_program_items_key"`, `program_items_before: "<missing key>"`, and `program_items_after` equal
  to the live Program's 2 items.
- `mutation.plan_items_created` contains only rows for `week_number` = the current week (4), plus any already
  existing future weeks of the window. No past weeks.
- `mutation.plan_items_attached_to_week` is `[]`.
- `mutation.plan_weeks_created` is empty, or contains only `past_gap_empty` weeks (empty PlanWeeks for weeks
  that were never opened; this is the existing #301 runtime behaviour).
- `before.current_week_plan_items` = 0, and `after.current_week_plan_items` ≥ 1.

The WARNING line `plan_convergence_repair {...}` on stderr is the loud log the runtime emits.

**3. Apply, to that identity only.**
```bash
docker compose -p pullup-staging exec app python scripts/repair_plan_convergence.py --telegram-id <OWNER_TG_ID> --apply > apply.json
docker compose -p pullup-staging exec app python scripts/repair_plan_convergence.py --telegram-id <OWNER_TG_ID> --apply   # must say "nothing to do"
```

**4. AFTER (read-only).**
```bash
docker compose -p pullup-staging exec app python scripts/qa_state_snapshot.py --telegram-id <OWNER_TG_ID> > after.json
```
Expected:
- `diagnoses` is empty.
- The inclusion has `snapshot_has_program_items_key: true` and `snapshot_program_items_count: 2`, and is still
  `is_active: true`, with the same `started_at` as in `before.json`.
- `current_week_plan_item_count` ≥ 1.
- `sessions` is unchanged against `before.json` (the completed historical session is still there).

Progression is checked by the tool's guards: any change to `progression_state` or `initial_progression_state`
aborts with exit code 4.

**5. UI on the real iPhone.** Open the Mini App and go to Планы. Expect «Неделя 4 · … · 0 из N» (not «0 из 0»)
with «Начать». Tap «Начать» → pre-screen «Начать» → Live → log a set → finish → Журнал. Reload; the
counter now shows «1 из N».

Optional automated version on the QA identity:
```bash
./qa-staging.sh provision
```
Then run `S-OWNER-01|S-OWNER-02` from `webapp-frontend/e2e-staging` (see `docs/STAGING_QA_HARNESS.md`).

## Exit codes of the repair tool

| Code | Meaning |
|---|---|
| 0 | ok, or nothing to do |
| 2 | no such user |
| 3 | the user has no plan |
| 4 | a guard was violated; everything was rolled back, even with `--apply` |

## Local rehearsal (done, not a substitute for staging)

The rehearsal is in `docs/audit/convergence-rehearsal/`: the same sequence on a staging-shaped database.
- The identity is `qa_aged_legacy_snapshot`, created by the real provisioner with **the pre-fix code**.
- Планы was then opened once on the pre-fix code, so the current-week PlanWeek exists with 0 rows, as on the
  owner's staging account.

Sequence and results:
1. `01-before-snapshot.json`: the same 4 diagnoses as staging. The current week is 5 instead of 4, because the
   identity is 23 days old.
2. `02-dry-run.json`: 1 snapshot key, 2 rows in the current week, no guard violations. Nothing was written.
3. `03-apply.json`: applied.
4. `04-apply-again.json`: «nothing to do».
5. `05-after-snapshot.json`: no diagnoses; the 2 completed sessions are kept.
6. Screenshots: S-OWNER-01 and S-OWNER-02 passing against that DB (Chromium against a local server on that DB; telegram.org — the real SDK script — is unreachable from the sandbox).
   - `s-owner-02-plans-before.png`: «0 из 3» with «Начать».
   - `s-owner-02-live.png`: Live.
   - `s-owner-02-plans-after.png`: «1 из 3».
