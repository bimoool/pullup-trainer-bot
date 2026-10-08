# TRAINING_SESSION_V2 — canonical session, Journal and Analytics

Index: [README.md](README.md). Prescription: [WORKOUT_DOMAIN_V2.md §5](WORKOUT_DOMAIN_V2.md#5-versions-and-snapshots).
Execution: [LIVE_ENGINE_V2.md](LIVE_ENGINE_V2.md). Plan credit: [PROGRAM_PLAN_V2.md §5](PROGRAM_PLAN_V2.md#5-plan-planweek-planitem-completion-credit).

## 1. One entity

Live execution and manual/post-factum logging write **the same** `TrainingSession` tree
(`training_sessions` → `session_blocks` → `set_targets` / `set_logs`). There is no second
history model for new data; legacy `workouts`/`elective_workouts` are converged into it (MIGRATION §4).

## 2. Fields and sources

```
TrainingSession
  id, user_id
  kind                 strength | external_activity
  source               planned_live | direct_live | manual_existing_workout | manual_custom | external_activity
  origin               native | legacy_backfill | legacy_elective        (provenance of the row, not a source)
  status               active | completed | cancelled
  workout_definition_id          int | null   (FK complexes)
  workout_definition_version_id  int | null
  prescription_snapshot          JSONB        required for kind=strength (WORKOUT §5)
  program_inclusion_id           int | null
  plan_item_id                   int | null   at most one credited occurrence (PL2)
  performed_at         UTC ts      anchor of the local calendar day
  started_at, ended_at UTC ts | null
  duration_seconds     int | null  authoritative duration
  duration_source      measured | entered | unknown
  timezone             IANA name at creation
  effort               1..5 | null      (session RPE scale already in use)
  comment              ≤ 1000 | null
  activity_type        external only (running, cycling, …)
  distance_meters      external only, optional
  spacing_violation    bool
  revision             int, +1 per edit
  engine_version       1 | 2 | null
```

Source rules (set at creation, never inferred later):

| source | Created by | workout_definition_id | snapshot | plan_item_id | progression |
|---|---|---|---|---|---|
| `planned_live` | live start from a PlanItem | from PlanItem | resolved at start | the PlanItem | if program main slot |
| `direct_live` | Workout Detail «Начать» | the workout | resolved at start | **null** (PL3) | no |
| `manual_existing_workout` | «Тренировку из моих» / post-factum of a known workout | **required** | built server-side from the chosen version at save | optional, only if user picks an occurrence | only if program main slot and owner of progression accepts (§5) |
| `manual_custom` | free-form strength log without a workout | null | synthesized from entered sets (`prescribed = performed`, `kind: unprescribed`) | null | no |
| `external_activity` | «Другую активность» | null | none | null | no |

Fix for D9 (post-factum loses identity): the manual API takes `workout_definition_id` (+ optional
`version_id`); the server builds the snapshot exactly as live start does
(`build_workout_snapshot`), stores `set_targets` from it and `set_logs` from the entered values.
Title, editability, «Открыть тренировку», workout history and exercise analytics all follow from
the stored identity and snapshot. **Clone** creates `source = manual_existing_workout` (or
`manual_custom` if the original had no definition) with the original's snapshot and **without**
`plan_item_id` (D10).

## 3. Set records and duration

```
SessionBlock  order_index, block_key, exercise_id (from snapshot), started_at, ended_at, status
SetTarget     prescribed set (copied from snapshot; set_index, kind, target, load, rest)
SetLog        set_index, round_index | null, actual_reps | actual_seconds, load_actual,
              effort, note, status performed | not_performed, is_extra, logged_at
```

- **R1** Every prescribed set has exactly one `SetTarget`; one `SetLog` per performed set; a
  prescribed set not performed (early finish) has `status = not_performed`. Block B 4 × 3 + max
  ⇒ 5 `SetTarget` rows, 5 `SetLog` rows when completed (J4).
- **R2** `is_max_set` is a property of the target (`kind = max_reps`) and is preserved on
  persistence (D3).
- **R3** Duration: live → `active_elapsed_ms` from the engine (pauses excluded),
  `duration_source = measured`; manual → optional user-entered minutes (`entered`) else `unknown`;
  external → required (`entered`). `completed_at − performed_at` is **no longer** the duration rule.
- **R4** Editing the date moves `performed_at` (and `started_at/ended_at` by the same delta) but
  never changes `duration_seconds` (D13).

## 4. Editability (one predicate)

| Session | Editable fields |
|---|---|
| `direct_live`, `manual_existing_workout`, `manual_custom` | date, duration, effort, comment, set actuals/effort/notes, add/remove extra sets |
| `planned_live` / any session consumed by progression | date, duration, effort, comment, notes. Set actuals read-only (they fed progression; progression is not recomputed retroactively — current rule kept) |
| `external_activity` | date, duration, activity_type, distance, effort, comment |
| `active`, `cancelled` | none |

- **ED1** The predicate is a pure domain function returning `can_edit`, `can_delete` and a reason;
  the API serialises it; the frontend has no heuristics (current rule kept).
- **ED2** Every edit increments `revision`; derived views recompute (§6 A7).
- **ED3** The snapshot is never edited.

## 5. Progression boundary

Only `planned_live` sessions of a program `main` slot apply progression, exactly once (current
`complete` idempotency kept), using actuals of working sets + max set. Manual logging of a main
session post-factum does **not** apply progression in Waves 1–3 (current behaviour); changing that
is outside this contract.

## 6. Journal and Analytics (derived)

One predicate feeds every view:
`canonical_sessions(user, range) = status = completed ∧ not archived ∧ not superseded`
(superseded = a legacy row converged into a native row; MIGRATION §4).

- **A1** `total_workouts` = `count(distinct session.id)` over `canonical_sessions` — an
  **integer**; Journal calendar, Profile and Analytics use the same function (D14).
- **A2** Category distribution attributes each session to **exactly one** category:
  `primary_category(session)` = category of the workout definition if set; else the category of
  the block with the most performed sets (tie → first block); external → «Другая активность».
  Rows sum to the total. Fractional shares may exist internally (e.g. for an “exercise mix”
  analysis) but no API field rendered as a workout count is fractional (D11).
- **A3** Labels are `display_name`s of `ExerciseCategory`/`Exercise` (WORKOUT E1); no slugs (D12).
- **A4** Exercise history groups by `analytics_identity(exercise)` (WORKOUT E2) and metric, and
  includes **all** sources with actuals (planned/direct/manual), so manual and live sessions of the
  same workout/exercise share one history (J8, J10).
- **A5** Minutes: `total_minutes = round(Σ duration_seconds / 60)`; weekly/category series are
  computed in seconds and rounded with largest-remainder so they sum to the total. Sessions with
  `duration_source = unknown` are counted in `without_duration`, never as 0 minutes silently (D13).
- **A6** Exactly one row per real workout: legacy rows that have a native copy are excluded by the
  `superseded` flag, not by per-endpoint fingerprints (D14).
- **A7** Analytics and Journal are recomputed from sessions on read (or cached keyed by
  `(user, max(revision), count)`); an edit is visible on the next read in every view (J10).
- **A8** External activities appear in the Journal timeline and in workout/minute totals, never in
  exercise history or strength metrics.

## 7. External activity boundary

External activity is a `TrainingSession(kind = external_activity)`: same timeline, same counts,
same edit/delete predicate; **no** WorkoutDefinition, blocks, snapshot or plan credit. It does
not pretend to be a strength workout.
