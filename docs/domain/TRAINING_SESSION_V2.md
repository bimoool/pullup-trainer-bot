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
| `planned_live`, `direct_live`, `manual_existing_workout`, `manual_custom` — including sessions of a course/program, of a PlanItem and with STEP-role blocks | date, duration, effort, comment, set actuals/effort/notes (the MAX set included) |
| `external_activity` | date, duration, activity_type, distance, effort, comment |
| `active`, `cancelled` | none |

- **ED1** The predicate is a pure domain function returning `can_edit`, `can_delete` and a reason;
  the API serialises it; the frontend has no heuristics (current rule kept). Plan/program provenance,
  `source = planned_live` or a STEP role never restricts editing or cloning (owner decision, #307 final
  review B1): **only the explicit MAX-set measurement drives progression; a TrainingSession stores an
  editable historical fact; progression is forward-only and never rewrites history.** Deletion keeps the
  stricter safe-delete predicate (PROJECT_SPEC §3), unchanged.
- **ED1a** Editing an ordinary (non-MAX) set actual changes only the session (revision + 1); progression
  state, `progression_state_rev`, PlanItems and already issued prescriptions (`set_targets`, snapshots)
  stay byte-for-byte unchanged. Editing the MAX actual likewise only corrects the historical fact — no
  retroactive recomputation; how the latest corrected MAX reaches the next prescription is #305 (§10).
- **ED1b** Clone follows the general clone rule (§2/D10) for course/planned sessions too: no
  `plan_item_id`, no `program_inclusion_id`, progression untouched. Note: a clone keeps the original's
  blocks, so a clone of a course session (STEP-role blocks with logged sets) counts as a performed MAIN
  start for rest spacing (`main_session_predicate`, PROGRAM_PLAN §4) on its date — it is a real
  pull-up workout; it never credits an occurrence.
- **ED2** Every edit increments `revision`; derived views recompute (§6 A7).
- **ED3** The snapshot is never edited.

## 5. Progression boundary

Only `planned_live` sessions of a program `main` slot apply progression, exactly once (current
`complete` idempotency kept), at completion, forward only. **Canonical (owner decision, #307 B1): only the
explicit MAX-set result is the measurement that drives the next prescription; ordinary working-set
actuals do not drive progression; already generated workouts are never regenerated.** (Known gap, #305:
the current STEP `weak_streak` still reads working-set volume — follow-up N7.) Manual logging of a main
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

## 8. Completion interface (Wave 3a #307 → Wave 2 #306)

One write boundary; the engine never writes several legacy tables itself.

| | |
|---|---|
| Entry | `LiveSessionService.complete_session(session_id, user_id, abandoned, effort=None, comment=None, active_elapsed_ms=None)`; HTTP `POST /api/v2/sessions/live/{id}/complete` `{abandoned, effort?, comment?, active_elapsed_ms?}` |
| Required | `session_id` of a `STARTED` session of `user_id`, `abandoned` (early finish: unperformed targets stay `not_performed`, progression skipped) |
| Optional | `effort` 1–5, `comment` ≤ 1000, `active_elapsed_ms` (engine-measured active time, pauses excluded; 0…24 h) |
| Transaction | the caller's request transaction; the session row is locked (`SELECT … FOR UPDATE`, same lock as `sets:batch`/start/finish), status re-read under the lock |
| Idempotency | the session id is the key: a repeated completion (retry, lost response, double flush, concurrent request) returns the same session, `progression_skipped_reason = already_completed`, no second progression, duration/credit unchanged; review fields fill only empty values |
| Result | `status = completed`, `completed_at = ended_at = now`, `duration_seconds`/`duration_source` (R3: `active_elapsed_ms` → `measured`; without it wall clock `started_at → ended_at` within [1 min, 6 h], else `unknown`) — written in exactly one place, `TrainingSessionRepository.mark_completed`, which every completion path (complete, finish interval, lazy interval finalisation) goes through |
| Credit | unchanged by completion: `plan_item_id` is fixed at start (PL2/PL3); completion never adds or moves it |
| Errors | unknown/foreign session → 404 (no disclosure); invalid body → 422 |

Session creation fields (`source_v2`, `kind`, definition/version, `prescription_snapshot`, `started_at`,
`timezone`, `program_inclusion_id`, `engine_version`) are written at start by
`TrainingSessionV2Service.stamp_new` (live start) — #306's start path calls the same function with
`engine_version = 2`. Manual/post-factum writes go through `ManualSessionService.record`
(`client_session_id` = idempotency key: same key → same session; key of another user → 422).

## 9. Read contract for Journal/Analytics (Wave 3b #308)

Everything below is derivable from `training_sessions` + blocks/targets/logs alone (no legacy join):

- **Identity of a completed workout:** one row per `training_sessions.id` with `status = completed`;
  `origin` tells native rows from legacy copies (`legacy_backfill` rows are exactly today's
  `_backfilled_fingerprint` set — #308 replaces the fingerprint by `origin` + `superseded_by_id`, A6).
- **Source workout:** `workout_definition_id` (+ `workout_definition_version_id` when the snapshot came
  from a version), `prescription_snapshot.title`, `source_v2`.
- **Chronology:** `performed_at` (+ `timezone` of creation for the local day; NULL on history → profile tz).
- **Duration:** `duration_seconds` with `duration_source`; `unknown` counts in `without_duration`,
  never as 0 (A5). History is backfilled with exactly the minutes analytics already showed.
- **Performed work:** `app.services.training_session_v2.block_outcomes(block)` (pure, `set_outcomes` in the
  domain) — per prescribed set: target, actual, `performed | not_performed`, `is_max_set` (from the
  target, R2); then extra sets (`is_extra`). Reps/volume = Σ actual of performed outcomes; load —
  `set_logs.load_actual` when the engine writes it (NULL on history: not invented).
- **Exercise identity:** `prescription_snapshot.blocks[].analytics_exercise_id` (E2), falling back to
  `session_blocks.exercise_id`.
- **Plan credit:** `plan_item_id` (explicit) ∪ legacy `session_plan_items` (read-only history) —
  `TrainingSessionRepository.credited_plan_item_ids`.
- **No double count:** a session is one row; clones are separate rows by design (new session, no credit).
  API: `GET /api/v2/sessions` returns these fields plus `blocks[].outcomes`, `editable_fields`, `can_clone`.

## 10. Seam with course prescription (#305)

#307 does not compute prescriptions. It records whatever the start path wrote as `SetTarget`
(including `is_max_set` targets) and derives the snapshot from them (`provenance.kind = progression`,
`program_inclusion_id`) when no version snapshot matches. When #305 lands: (1) its `upsert_set_logs_batch`
`is_max_set` inheritance and the read-side inheritance here agree (both by planned-set order); (2) set
kinds are already stored (`set_targets.kind`); (3) a progression-resolved snapshot built with
`build_prescription_snapshot(resolve_progression=…)` can replace the synthesized one at start without a
schema change (`prescription_snapshot` is JSONB; `workout_definition_version_id` nullable). Alembic:
#305's `e3b9c5d7a2f1` and this `f4c1a7e9b3d2` both revise `d8a3c6f1e2b4`; whichever merges second
rebases its `down_revision` (MIGRATION §9.1 — no parallel heads).

**Corrected MAX values (seam for #305).** A Journal edit of a MAX set (`set_logs.value` of a set whose
target `is_max_set`) is a historical correction only: #307 persists it, bumps `revision`, and changes no
progression state, PlanItem or prescription. #307 emits no event and recomputes nothing. When/whether the
latest corrected MAX of the current cycle feeds the **next** prescription is decided by #305 at its forward
boundary (it can read `set_logs` + `set_targets.is_max_set` and the session `revision`); past cycles and
completed workouts are never regenerated. The pre-existing explicit endpoint
`POST /api/v2/program-inclusions/{id}/progression/{preview,apply}` (legacy cascade replay) is not called by
any edit path and is outside this decision.

## 11. Implementation decisions (Wave 3a, to confirm in review)

- **ED1 (superseded reading, #307 final review B1):** an earlier reading made sessions "consumed by
  progression" (course link, `program_inclusion_id`, STEP role, unproven `planned_live`) metadata-only and
  non-cloneable. The owner rejected it: only the MAX set drives progression, forward-only — see §4 ED1/ED1a/ED1b.
- **Status vocabulary:** the existing `started | completed` enum is kept (`started` = contract `active`).
  `cancelled` is not introduced: adding a PG enum value would break the previous image on rollback
  (old code cannot read it). An abandoned live session that the user completes stays `completed` with
  `not_performed` targets; one never completed stays `started` and is not counted.
- **Legacy rows not named by MIGRATION §3:** `freeform` without snapshot/activity → `direct_live` if it has
  a `client_session_id` (a live start), else `manual_custom`; `POST /sessions source=plan` (one-shot
  program record, QA path) → `planned_live`.
- **Snapshot vs targets:** a version snapshot is stored only if it agrees with the written `SetTarget`
  (same exercises in order, same set counts); otherwise the snapshot is synthesized from the targets
  (`synthesized = true`) so it never contradicts R1. With #306 building targets from the snapshot the two
  always agree.
- **Clone duration:** strength copy → `unknown` (not measured); external activity copy → entered value copied.
