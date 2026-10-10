# MIGRATION_V2 — from current structures to the v2 contract

Index: [README.md](README.md). Rules: `.claude/skills/migrations-safe` (additive only), constitution
Principle V (archive, don't delete), `docs/deploy.md` (archive-table incident),
`docs/ARCHITECTURE_RECOVERY_AUDIT.md` (T1–T7 convergence), `docs/STAGING_CONVERGENCE_RUNBOOK.md`.

Lesson driving this plan: «fresh works, aged breaks». Every step below is proven on an
**aged-shaped** dataset (rehearsal §8) before it is proven on a fresh DB.

## 1. What stays, what is added

| Current | v2 fate | Change (additive) |
|---|---|---|
| `exercises` | stays | `display_name` (backfilled from `name`), `slug`, `category_id`, `subcategory_id`, `visibility`, `analytics_exercise_id` |
| — | new `exercise_categories` | seeded; maps every existing category/subcategory string (`pull_ups`, `Подтягивания`, `user`, `block_a`, `elective_*`, …) to one row with a display name |
| `complexes` / `complex_items` | stay as WorkoutDefinition head | `complexes.current_version_id`; `complex_items` kept as editable head |
| — | new `workout_definition_versions` | backfilled: one version per existing complex from V1 protocols (WORKOUT §8) |
| `programs`, `program_items` | stay | `programs.slots` JSONB (or `program_slots` table), `frequency`, `constraints`, `assessment`; `config.min_rest_days` becomes the read source |
| `program_inclusions` | stay | `progression_state_rev`, `sequence_cursor`, `baseline_assessment_result_id`, `status`; `progression_state.block_b.work_sets` backfilled (= `STRENGTH_BLOCK.work_sets` = 4) |
| `training_plans`, `plan_weeks` | stay | — |
| `plan_items` | stay; new rows are occurrences | `workout_definition_id`, `occurrence_index`, `scheduled_date`, `program_slot_key`, `custom_plan_id`, `status`, `legacy_aggregate bool` |
| — | new `custom_plans` | — |
| `training_sessions` | stays, becomes canonical | `kind`, `source_v2`, `origin`, `workout_definition_id`, `workout_definition_version_id`, `prescription_snapshot` (new column; `workout_snapshot` kept read-only), `plan_item_id`, `program_inclusion_id`, `started_at`, `ended_at`, `duration_source`, `timezone`, `distance_meters`, `spacing_violation`, `revision`, `engine_version`, `superseded_by_id`, phase fields of LIVE §1 |
| `session_plan_items` (M2M) | stays read-only for history | new writes use `plan_item_id` |
| `session_blocks`, `set_targets`, `set_logs` | stay | `block_key`, `status`, `ended_at`; `set_targets.kind`; `set_logs.round_index`, `status`, `load_actual` |
| — | new `session_events` | append-only engine log |
| legacy `workouts`, `blocks`, `workout_sets`, `baselines`, `equipment_items`, `elective_workouts`, `workout_drafts` | **frozen** after cutover (read-only), never dropped in this campaign | none → their `*_archive_admin_reset` tables need **no** change (CLAUDE.md rule satisfied) |

No column is renamed, retyped or dropped in Waves 1–4. Contraction (dropping legacy columns) is a
separate, later decision.

## 2. Phases

1. **Expand** — additive schema per wave (nullable / defaulted). Old code keeps working.
2. **Backfill** — deterministic data migration or script (§3), idempotent, natural keys.
3. **Converge** — `converge_user_domain_v2(user, today)` (§5) makes each aged user's derived
   state equal to what a fresh user would get with the same history.
4. **Dual-read** — new readers behind a flag (`DOMAIN_V2_PLAN`, `DOMAIN_V2_ENGINE`,
   `DOMAIN_V2_HISTORY`), compared to old readers by an invariant checker in staging.
5. **Cutover** — flag on; writers switch; legacy writers redirected to v2 (§4).
6. **Freeze** — legacy tables read-only (DB grants or repository guard).

## 3. Deterministic backfill rules

| Target | Rule | Ambiguity handling |
|---|---|---|
| `workout_definition_versions` | V1 protocol → v2 content (WORKOUT §8); re-run is a no-op because content equal to the *current* version creates nothing (append-only, WORKOUT §5) | V1 interval not divisible → logged, version not created, workout flagged for review |
| W-ladder system workout | new version with explicit 17-set ladder; old sessions keep their snapshot | — |
| `exercise_categories` + `analytics_exercise_id` | table of string → category id; role/elective exercises → public «Подтягивания» | unknown strings → «Без категории» row, reported |
| `program_inclusions.progression_state.block_b.work_sets` | absent → 4 (revision `e3b9c5d7a2f1`, #305; `null` = absent) | present → untouched |
| `training_sessions.source_v2` | `plan` → `planned_live`; `freeform` + snapshot → `direct_live`; `freeform` + `activity_type` → `external_activity`; `backdated` + snapshot → `manual_existing_workout`; `backdated` without snapshot → identity recovery (next row); `elective` → `manual_existing_workout` with `origin = legacy_elective` | — |
| Identity recovery for old backdated sessions (D9 history) | recover `workout_definition_id` **only if** exactly one of the user's workouts (live or archived, at a version current at `performed_at`) has an identical ordered exercise list; record `identity_recovered_by = exact_match_v1` | 0 or ≥ 2 matches → `manual_custom`, never guessed |
| `prescription_snapshot` for sessions without one | synthesize from `set_targets` + exercise names, `synthesized = true` | missing targets → `kind: unprescribed` |
| `duration_seconds` | `activity` → existing value; others with `completed_at − performed_at` in 1 min…6 h → that value, `measured`; else `unknown` | — |
| `plan_item_id` | the single linked PlanItem if exactly one; STEP sessions with 2 role items → the occurrence created by plan conversion (§5) | otherwise null (no credit invented) |
| `plan_items` aggregate rows | past weeks: `legacy_aggregate = true`, counted as `count_per_week` for display; current/future weeks: expanded to N occurrences by `converge_user_plan` | — |

Every backfill: deterministic order (`ORDER BY id`), natural/unique keys, `ON CONFLICT DO
NOTHING`, dry-run mode printing counts, apply-again ⇒ 0 changes.

## 4. Single history (legacy convergence)

Today analytics, Journal and Profile disagree (D14). Target: `training_sessions` is the only
history read by any v2 view.

1. Every legacy `workouts`/`elective_workouts` row has exactly one native copy (extend
   `scripts/backfill_multi_program.py`, keyed by `(origin, legacy_id)` unique).
2. **Before** cutover, legacy writers (`WorkoutLogService`, `ElectiveLogService`, legacy
   edit/delete) also write/update/delete the native copy in the same transaction (dual-write).
3. Views read `canonical_sessions` (TRAINING_SESSION §6) — no more `exclude_backfilled`
   fingerprints. Legacy cascade/readiness logic keeps reading legacy tables until the bot path is
   retired (out of this campaign).

## 5. Aged-state convergence

`converge_user_domain_v2(user, today)` — one idempotent function, extending
`converge_user_plan` (recovery audit T2) and `scripts/repair_plan_convergence.py`:

1. normalise inclusion snapshot/state (T1) + `block_b.work_sets`;
2. expand current/future aggregate PlanItems to occurrences, preserving existing credits
   (an aggregate row with k completed sessions → k completed occurrences linked to those sessions,
   in `performed_at` order);
3. compute `last_main_session_at` from canonical sessions;
4. set inclusion `awaiting_assessment` only if no valid assessment **and** no completed main
   session (aged users with history are never pushed back to assessment).

Invoked by the deploy-time script for all users and by login/`GET /plan` **only** via the same
function (no other lazy writes). **Wave 1b (#304):** the plan part is `app.services.plan_convergence
.converge_user_plan` (steps 2–3 here; rules in PROGRAM_PLAN_V2 §10.8); the deploy-time runner is
`scripts/repair_plan_convergence.py --all [--apply]` (dry-run by default, per-user transaction, guards:
history/subscription/access unchanged, only the allowed #304 mutations; apply-again = 0 mutations). Revision
`d8a3c6f1e2b4` itself only adds columns/tables and backfills literal SQL (`plan_items.source`,
`workout_definition_id = complex_id`, inclusion `status`, `training_sessions.plan_item_id` for single-link
sessions, the «Подтягивания» slots/frequency/constraints/assessment); downgrade drops exactly those (explicit
credit, custom plans, occurrence markup — occurrence rows remain as ordinary rows; retired aggregates reappear
to old code), re-upgrade restores the derivable backfill. Invariant checker (`--dry-run`) asserts after convergence:
fresh-equivalence (a fresh user replaying the same events gets the same derived state) for the
rehearsal profiles.

## 6. In-flight sessions and clients

- `active` sessions at cutover keep `engine_version = 1` and finish on the v1 path; new starts use v2.
- Old Mini App bundles (cached WebView) talking to new API: v2 endpoints are additive; v1 live
  endpoints remain until Wave 4 acceptance; offline queues from v1 clients are accepted by v1 endpoints.

## 7. Subscription / access preservation

No migration in this campaign writes `users.subscription_*`, `subscriptions` or
`programs.access_level`. The rehearsal compares, before/after: count of entitled users,
`subscription_expires_at` per user (exact equality), `access_level` per program.

## 8. Rehearsal and rollback

Rehearsal (per wave, mandatory before staging cutover), following
`docs/audit/convergence-rehearsal/` (01 before-snapshot → 02 dry-run → 03 apply → 04 apply-again →
05 after-snapshot):

- dataset: anonymised production-shaped dump **plus** the aged QA profiles (backfill-era user
  from 19.09, expired subscription, active payer, user with legacy + v2 history, user with
  deleted/archived workouts, user mid-session);
- pass criteria: 04 = zero changes; invariant checker clean; acceptance journeys J1–J12 pass on
  both a fresh and an aged profile (J2).

Rollback: schema is additive, so **code rollback** to the previous image is always safe; backfill
writes only new columns/tables and is not reverted. Flags allow turning a reader/writer off without
redeploy. Dual-write keeps legacy tables authoritative until cutover, so rollback before cutover
loses nothing. After cutover, rollback = flag off + legacy reads (native rows written meanwhile are
already mirrored to legacy by dual-write until freeze; freeze happens only after Wave 4 sign-off).

**Schema downgrade is not code rollback.** Downgrading the schema below a revision that created v2
tables (first: `b7d2e9f4a1c3`, WORKOUT §9.13) drops those tables: v2 version history created after
the upgrade is lost, and a re-upgrade rebuilds only what can be derived from the surviving V1 heads
plus that revision's frozen literals. Never promise that arbitrary user version history survives a
schema downgrade → upgrade cycle.

## 9. Implementation waves and parallelization

Issues: umbrella and wave issues are listed in [§9.2](#92-github-issues).

### 9.1 Order and ownership

```
Wave 1  Program + Plan foundation       (core models; single writer)
  1a WorkoutDefinition v2 + versions + snapshot + exercise identity   ← first, everything depends on it
  1b Program/Plan occurrences + constraints + custom weekly volume     ← after 1a schema merged
  1c Course prescription correctness (block B, max set, init rule)     ← after 1a; OD-1 for numbers (OD-3 resolved)
Wave 2  Live Engine v2                    ← after 1a (snapshot shape) + 1b (start preconditions)
Wave 3  TrainingSession / Journal / Analytics
  3a Session contract + manual identity + editing                     ← after 1a; parallel with Wave 2
  3b Analytics/Journal derivation + legacy convergence                ← after 3a
Wave 4  Integration + aged rehearsal + real-device acceptance         ← after 2, 3b
```

Parallelism rules:

- **Never two writers on the same core model.** Owner of `app/domain/workout_*`,
  `models_program.py` WorkoutDefinition/Exercise tables: Wave 1a. Plan/Program tables: 1b.
  `training_sessions` columns: Wave 3a adds them in **one** migration that Wave 2 consumes
  (Wave 2 adds only engine columns + `session_events`, sequenced after 3a's migration merges).
- Alembic heads: each wave rebases its migration on the latest merged head; no parallel heads.
- Safe in parallel after 1a merges: **Wave 2** (engine: `app/domain/live_engine*`,
  `services/live_session.py`, live screens) ∥ **Wave 3a** (session write paths, `session_log.py`,
  `session_editing.py`, journal forms). Shared file `routes_v2.py` → split routers first
  (mechanical, done at start of Wave 2 by the Wave 2 owner).
- Wave 3b ∥ late Wave 2 (analytics files are disjoint).

Branches/worktrees (one worktree per active wave, base = latest integration branch):
`wave1/workout-definition-v2`, `wave1/program-plan-v2`, `wave1/course-prescription`,
`wave2/live-engine-v2`, `wave3/session-contract`, `wave3/analytics-journal`,
`wave4/integration-acceptance`. Integration order: 1a → 1b → 1c → 3a → 2 → 3b → 4.

Model choice: **Opus 5.5** for 1a, 1b, 2 (state machine, races, offline replay), 3a migrations
and convergence (§5), Wave 4 integration. **Sonnet 5.5** for isolated slices with a fixed
contract: display function `describe()` + golden tests, category seed table, custom-plan UI,
analytics rounding/labels in 3b, audio-hook subscriber UI.

### 9.2 GitHub issues

Umbrella: bimoool/pullup-trainer-bot#302. All `status:backlog` (not `ready`: the orchestrator
must not pick them up until the owner promotes them).

| Wave | Issue | Severity | Depends on | Journeys |
|---|---|---|---|---|
| 1a WorkoutDefinition v2 | bimoool/pullup-trainer-bot#303 | P0 | — | J3, J1 |
| 1b Program + Plan foundation | bimoool/pullup-trainer-bot#304 | P0 | #303; OD-2 value | J6, J7, J11, J12, J2 |
| 1c Course prescription correctness | bimoool/pullup-trainer-bot#305 | P0 | #303, #307 (Alembic parent); OD-1 numbers | J4, J1, J2 |
| 2 Live Engine v2 | bimoool/pullup-trainer-bot#306 | P1 | #303, #304, #307 migration | J5, J1, J3, J4 |
| 3a TrainingSession v2 | bimoool/pullup-trainer-bot#307 | P0 | #303, #304 (∥ #306) | J8, J9, J10, J7 |
| 3b Journal + Analytics | bimoool/pullup-trainer-bot#308 | P1 | #307 (∥ late #306) | J10, J2, J1, J9 |
| 4 Integration + acceptance | bimoool/pullup-trainer-bot#309 | P1 | #306, #308 | J1–J12 |
| Owner decisions OD-1…OD-4 | bimoool/pullup-trainer-bot#310 | — | — | — |
