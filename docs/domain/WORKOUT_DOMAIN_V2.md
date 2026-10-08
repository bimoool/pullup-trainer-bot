# WORKOUT_DOMAIN_V2 — Exercise, WorkoutDefinition, prescription, snapshot

Index and decision log: [README.md](README.md). Supersedes the *definition shape* of
`adr/WORKOUT_PROTOCOL_V1.md` (V1 stays readable as `schema_version = 1`, §8).

## 1. Ownership

| Concept | Owner (writes) | Storage (current → v2) |
|---|---|---|
| Exercise | system seed migration / user (own exercises) | `exercises` (+ fields §2) |
| ExerciseCategory | system seed migration | new `exercise_categories` (§2) |
| WorkoutDefinition (mutable head) | system seed migration / owning user | `complexes` (no rename) |
| WorkoutDefinitionVersion (immutable) | domain service on every content change | new `workout_definition_versions` |
| Block (in a version) | part of version content | v2: inside version JSON; `complex_items` stays as the editable head |
| PrescriptionSnapshot | live/manual session creation (server) | `training_sessions.prescription_snapshot` (§5) |

Pure domain code (`app/domain/`) owns the types, normalization and resolution functions. No
aiogram/SQLAlchemy imports (constitution).

## 2. Exercise identity and display names

```
Exercise
  id                    int, stable, never reused
  slug                  str | null   INTERNAL ONLY (seed natural key); never serialized to UI fields
  display_name          str          required, human, Russian («Подтягивания»)
  category_id           FK exercise_categories
  subcategory_id        FK exercise_categories | null
  metric_type           reps | time
  visibility            public | internal | user
  owner_user_id         null for system
  analytics_exercise_id FK exercises | null   canonical identity for history/analytics
  archived_at           null | ts

ExerciseCategory
  id, slug (internal), display_name (required), parent_id, sort_order, is_service
```

Invariants:

- **E1** Any user-facing string for an exercise or category comes from `display_name`. API
  responses carry `{id, display_name}`; a slug in a user-facing field is a contract violation
  (test: no response field rendered as text matches `^[a-z_]+$`).
- **E2** History and analytics group by `analytics_identity(e) = e.analytics_exercise_id ?? e.id`.
  The internal role exercises «Подтягивания — объём» (block_a) and «— сила» (block_b) and the
  `elective_*` exercises point to the public «Подтягивания» exercise, so a pull-up is one
  exercise everywhere (fixes D12 split «Подтягивания» vs `pull_ups`).
- **E3** User exercises get a real category (default «Мои упражнения», a seeded category), never
  the raw string `"user"`.
- **E4** `display_name` changes are allowed; history shows the name frozen in the session
  snapshot (§5) for “what was done”, and the current name in aggregated analytics labels.

## 3. Block and set prescription (canonical, set-explicit)

A **WorkoutDefinitionVersion** content is:

```
WorkoutContent (schema_version = 2)
  title                 str
  default_rest_seconds  int | null            workout-level default between sets
  blocks: Block[]       ≥ 1, ordered

Block
  key                   str   stable within a definition ("A", "B", "b1"...) — used for identity across versions
  exercise_id           int
  kind                  sets | interval
  prep_seconds          int ≥ 0               before the block's FIRST work phase (§3.6)
  rest_after_block_seconds int | null         transition rest to the next block; null on last block
  extra_sets_allowed    bool  (default true for kind=sets)
  load                  LoadSpec | null       block default (bodyweight / band(item) / added_kg / assisted_kg)
  source                static | progression(role)   (§6)
  sets: SetPrescription[]     kind=sets only, ≥ 1 (static) or resolved at start (progression)
  interval: IntervalSpec      kind=interval only

SetPrescription                  one element = one set the user performs
  kind                  reps | max_reps | time | max_time
  target_reps           int ≥ 1      kind=reps only
  target_seconds        int ≥ 1      kind=time only
  load                  LoadSpec | null   overrides block load
  rest_after_seconds    int | null   rest after THIS set; null on the last set of the block
  role                  working | max | warmup   (default working)

IntervalSpec
  work_seconds          int ≥ 1
  rest_seconds          int ≥ 0
  rounds                int ≥ 1
  record_reps_per_round bool        (true for «3 минуты подтягиваний»: legacy recorded reps per interval)
```

### 3.1 Required expressiveness (examples are normative test vectors)

| Brief item | Canonical content |
|---|---|
| Fixed reps 3 × 10, rest 90 | `sets=[reps 10 r90, reps 10 r90, reps 10 r—]` |
| MAX / AMRAP | `sets=[max_reps]` — **no target field exists**; UI shows «Максимум», never «0» |
| W-ladder | 17 sets `reps` with `target_reps` = 5,4,3,2,1,2,3,4,5,4,3,2,1,2,3,4,5 (the product ladder `app/domain/electives.py:32`), rest 10 each, last `—`; displayed «5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5», total 53 |
| Timed work | `sets=[time 30, time 30]` (plank 2 × 0:30) |
| Interval | `interval{work 10, rest 20, rounds 6}` = «3 минуты подтягиваний» |
| Multi-block | `blocks=[A, B, …]` any mix of `sets`/`interval` |
| Block B 4 × 3 | Block B `sets` has **four** `reps 3` working sets (+ the `max` set, §6) — four rows execute and persist |
| Rest per set / block / workout | `rest_after_seconds` / `rest_after_block_seconds` / `default_rest_seconds` |
| Max ladder rest 180/120/60 | 4 × `max_reps` with `rest_after_seconds` 180,120,60,— (D17) |
| Optional extra sets | `extra_sets_allowed`; extra sets are logged, never prescribed (§4) |

### 3.2 Normalization (write-time, pure function)

`normalize(content) → content` runs on every save and produces the stored form:

1. Expand shorthand `{sets: N, reps: R}` / `{sets: N, seconds: S}` to N explicit elements.
2. Resolve rest: `set.rest_after_seconds ?? workout.default_rest_seconds ?? SYSTEM_DEFAULT_REST (90)`
   for every set except the last of a block (`null`).
3. Fill `prep_seconds` default (§3.6).
4. Validate invariants W1–W8 (§4). Invalid → 422, nothing stored.

Display (`describe(block)`) is a pure function of the stored form: uniform sets → «3 × 10»;
non-uniform → the explicit sequence «5-4-3-2-1-…»; max → «Максимум × 4». No component re-derives
`sets × reps` from a single number again.

### 3.3 Result entry per kind (consumed by LIVE §4)

| Set kind | Work phase ends by | Result entry |
|---|---|---|
| `reps` | user submits | required: actual reps (prefilled with target) |
| `max_reps` | user submits | required: actual reps (empty, no prefill) |
| `time` | deadline (auto) | optional correction of seconds; default = target |
| `max_time` | user stops | auto-measured seconds, editable |
| interval round | deadline (auto) | optional reps per round if `record_reps_per_round` |

### 3.4 Interval semantics

Total = `rounds × (work + rest)` (compatible with V1: 6 × 30 = 180 s, final rest included,
DONE at 180). `completed_rounds` = fully completed WORK phases. Per-round reps (D16) are
`SetLog` rows with `round_index`, so interval work is visible in exercise history.

### 3.5 Rest semantics

Rest belongs to the **preceding** set (`rest_after_seconds`). Between blocks:
`rest_after_block_seconds` (main «Подтягивания»: the legacy big break, 900 s,
`DEFAULT_BIG_BREAK_SECONDS`). A `null` rest means “no rest phase”, not “default”.

### 3.6 Preparation

`prep_seconds` applies **once per block, before its first work phase**. Defaults: 5 s for blocks
whose first set is `time`/`max_time` or `interval` (the user must be in position when the clock
starts); 5 s for the first block of a workout; 0 otherwise (the preceding rest is the
preparation). Authors may set any value ≥ 0.

## 4. Invariants

- **W1** `len(block.sets)` is the number of prescribed sets for that block — **no global sets
  field, no default of 1** (D2). Engine, persistence, display and progression all read it.
- **W2** `max_reps`/`max_time` sets have **no** target; `target_reps = 0` is never a plan.
- **W3** Exactly one of `sets`/`interval` per block, matching `kind`.
- **W4** `rest_after_seconds` is null **iff** the set is last in its block.
- **W5** `block.key` unique within a definition; stable across versions of the same definition.
- **W6** Every `exercise_id` is visible to the definition owner (system → public/internal; user →
  public or own).
- **W7** A `source=progression(role)` block has no `sets` in the definition; they are produced by
  the resolver at start (§6). A static block always has ≥ 1 set.
- **W8** Extra sets are never part of a definition or snapshot; they exist only as `SetLog.is_extra`.

## 5. Versions and snapshots

```
WorkoutDefinitionVersion
  id, workout_definition_id, version_no (1..), schema_version (2),
  content JSONB (normalized), content_hash (sha256 of canonical JSON), created_at
  UNIQUE (workout_definition_id, version_no); UNIQUE (workout_definition_id, content_hash)
```

- Saving a definition whose normalized hash equals the latest → no new version (idempotent).
- `complexes.current_version_id` points to the head. Archiving a definition never deletes versions.

```
PrescriptionSnapshot (stored on TrainingSession, self-contained)
  snapshot_schema        2
  workout_definition_id  int | null
  workout_definition_version_id int | null
  title                  str
  blocks[]: { key, exercise_id, exercise_display_name, analytics_exercise_id,
              category_id, kind, prep_seconds, rest_after_block_seconds, load,
              sets[] (resolved SetPrescription), interval }
  provenance: { kind: static | progression,
                program_inclusion_id?, strategy?, progression_state_rev?, resolved_at }
```

- **S1** Written once, at session creation (live start or manual save). Immutable afterwards —
  editing a session edits *actuals* only (SESSION §4).
- **S2** History renders from the snapshot, never from the mutable definition (a renamed or
  archived workout still shows what was prescribed).
- **S3** The snapshot is resolved: it contains concrete targets even for progression blocks, plus
  provenance; it never contains a `progression` source marker (V1 rule kept).
- **S4** Sessions created before v2 get a **synthesized** snapshot (`synthesized: true`) from
  `set_targets` + exercise names (MIGRATION §3).

## 6. The main «Подтягивания» workout (progression-sourced)

AD-3: one WorkoutDefinition «Подтягивания» with two blocks, matching the legacy pull-up workout
(`webapp-frontend/src/LiveWorkoutScreen.tsx:74-92`, `app/domain/constants.py:90-91,200-202`):

| Block | Resolved sets (for state `target_a=10, work_sets_a=3, target_b=3, work_sets_b=4`) |
|---|---|
| A (volume) | `reps 10 r240, reps 10 r240, reps 10 r240, max_reps r—`; `rest_after_block_seconds=900` |
| B (strength) | `reps 3 r180, reps 3 r180, reps 3 r180, reps 3 r180, max_reps r—` |

- The resolver `resolve_progression_block(role, progression_state) → SetPrescription[]` is pure and
  reads `work_sets` for **both** roles (`work_sets_b` must exist in state; MIGRATION §3 backfills
  `block_b.work_sets = 4` from `STRENGTH_BLOCK.work_sets`).
- The trailing `max_reps` set is **required input** of the current progression formula
  (`delta = max_reps − target`, `app/domain/progression.py:121`); without it progression cannot
  grow (D3). Owner confirmation that «4 × 3» means *4 working sets + the max set*: OD-3.
- Load comes from progression state (`equipment_type/value/item_id`) into `LoadSpec`.

## 7. Display contract (shared by plan, live, journal, analytics)

`describe(snapshot_block)` and `exercise_display_name` from the snapshot are the **only** sources
of block labels. Course blocks therefore always have names (D15). The same function feeds
Workout Detail, Plan card, Pre-screen, Live, Summary and Journal; one golden test per example in
§3.1 asserts identical strings on every surface.

## 8. Compatibility with V1 protocols

V1 (`ComplexItem.protocol`, 4 types) maps deterministically to v2 blocks:
`reps_sets{sets N, reps R, rest}` → N × `reps R`; `time_sets` → N × `time S`;
`max_effort{attempts N, rest}` → N × `max_reps`; `interval{total, work, rest}` →
`rounds = total / (work + rest)` (must divide exactly; otherwise reject as invalid V1 — none in
seed). `reps_sets{source: progression}` → `source = progression(role)`. The W-ladder seed row is
re-authored as the explicit 17-set ladder (new version; old sessions keep their snapshot).
