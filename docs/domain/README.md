# Domain contract v2 — index (Wave 0)

**Status:** Accepted architecture contract (Wave 0, 2026-10-08). Branch
`architecture/wave0-domain-contract`, base `4298f8b`. No product code changed in Wave 0.

This folder is the **canonical domain contract** for the training chain. Implementation waves
(1–4) implement it. Where these documents disagree with older docs (`PROJECT_SPEC.md` §2–§4,
`adr/WORKOUT_PROTOCOL_V1.md`, `architecture-multicourse.md`), **this folder wins for target
behaviour**. `PROJECT_SPEC.md` still describes **current** behaviour until each wave lands and
updates it in the same change.

## The chain

```
Exercise ─┐
          ├─▶ WorkoutDefinition ──(immutable)──▶ WorkoutDefinitionVersion
          │          ▲
Program ──┴── ProgramSlot[] (ordered refs to WorkoutDefinitions + roles + constraints)
   │
   ▼  enrol (ProgramInclusion: frozen snapshot + progression state)
Plan ── PlanWeek ── PlanItem (ONE concrete occurrence of ONE workout)
                       │ start (resolve prescription → PrescriptionSnapshot)
                       ▼
                 Live execution (engine state + ONE deadline)
                       │ complete
                       ▼
                 TrainingSession  ◀── manual / post-factum / external activity (same entity)
                       │
                       ▼ (derived, never stored as truth)
                 Journal timeline · Exercise history · Analytics
```

| Document | Owns |
|---|---|
| [WORKOUT_DOMAIN_V2.md](WORKOUT_DOMAIN_V2.md) | Exercise identity, WorkoutDefinition, block/set prescription, versions, PrescriptionSnapshot |
| [LIVE_ENGINE_V2.md](LIVE_ENGINE_V2.md) | Execution state machine, single clock, auto-transitions, pause/resume, audio hooks |
| [PROGRAM_PLAN_V2.md](PROGRAM_PLAN_V2.md) | Program, progression input, min-rest constraint, Plan/PlanWeek/PlanItem, custom weekly volume, access |
| [TRAINING_SESSION_V2.md](TRAINING_SESSION_V2.md) | TrainingSession, sources, set logs, editability, external activity, Journal + Analytics invariants |
| [MIGRATION_V2.md](MIGRATION_V2.md) | Expand → backfill → converge → cutover; aged users; rehearsal/rollback |
| [ACCEPTANCE_JOURNEYS_V2.md](ACCEPTANCE_JOURNEYS_V2.md) | J1–J12, the executable definition of “done” |

Each rule lives in exactly one document; others link to it.

## Source of the findings

Phase D artefacts (`PHASE_D_REPORT.md`, `MANIFEST.md`, `CODE_AUDIT_NOTES_4298f8b.md`,
`REFERENCE_TRACES.md`, `OWNER_IPHONE_FINDINGS.md`) live on the owner's Mac
(`~/pullup-audit-local/`) and were **not available** in the environment that authored Wave 0.
The defect list below is the Phase D findings as restated in the Wave 0 brief, **each re-traced
in code at `4298f8b`** (file:line below), plus `docs/FUNCTIONAL_AUDIT_WAVE_1.md` (FD-xx IDs).
When implementing, cross-check against the local Phase D files; a mismatch is a stop condition.

## Defect → root cause → contract (traceability)

| # | User-visible defect | Root cause at `4298f8b` | Contract |
|---|---|---|---|
| D1 | W-ladder shows/executes as «17 × 3» | `StaticRepsPrescription` has one `reps` (`app/domain/workout_protocol.py:82`); seed averages the ladder (`app/db/migrations/versions/a4c8e1f7b2d9_system_content_seed.py:98-101`) | WORKOUT §3 explicit per-set list |
| D2 | Course Block B «4 × 3» runs/persists as 1 set (FD-09) | `sets_count = role_state.get("work_sets", 1)` (`app/services/live_session.py:476`); `block_b` state has no `work_sets` (`app/services/program_inclusion.py:87-97`) | WORKOUT §3, §6 |
| D3 | v2 course progression never grows | STEP targets never set `is_max_set` (`live_session.py:479-482`), batch upsert hard-codes `is_max_set=False` (`app/db/repositories/training_sessions.py:382-385`) → `max_reps=0` (`app/services/session_log.py:78-83`) → `delta<0` in `_compute_raw_target` (`app/domain/progression.py:121`) | WORKOUT §3 (`max` set kind), PROGRAM §3 |
| D4 | Prep/rest countdown hits 0 and waits for «Готов»/«Пропустить отдых» | no auto-advance (`webapp-frontend/src/SessionLiveScreen.tsx:551-569`); spec §2 «переход — только действие пользователя» | LIVE §3 |
| D5 | Countdown jumps / two clocks | client picks among server `ends_at` (no clock offset), local constants 5/90, `endsAtOverride`, `pausedRemainingMs` (`webapp-frontend/src/offlineSession.ts:255-306`); client duplicates server `next_phase` (`offlineSession.ts:63-101`) | LIVE §2 |
| D6 | 3 main sessions per week regardless of rest days; next-day start possible | v2 start has no readiness check (`live_session.py:200-295`); `config.min_rest_days` unread; program = 2 items × `count_per_week=3` free pool | PROGRAM §4 |
| D7 | Fresh max = 8 → «10 × 3» bodyweight | program-era state ignores baseline (`program_inclusion.py:60-99`, default `VOLUME_BLOCK.base_target=10`, `equipment=BODYWEIGHT`) (FD-17) | PROGRAM §3 + owner decision OD-1 |
| D8 | Future-week course workouts cannot be started | `_reject_future_week_course_item` 422 (`live_session.py:297-307`) | PLAN §6 |
| D9 | Post-factum «Тренировка из моих» → «Тренировка», not editable, absent from exercise analytics | payload has no `workout_id` (`webapp-frontend/src/journalLog.ts:123-138`), `SessionCreateRequest` has no field (`app/web/schemas_v2.py:344`), no snapshot written (`repositories/training_sessions.py:164-195`) → title `None` (`app/web/routes_v2.py:1231`), deletion/edit predicate `REASON_UNPROVEN`, analytics skip `protocol_type is None` (`app/domain/training_analytics.py:242`) | SESSION §2, §4 |
| D10 | Clone of a plan session credits the plan | `clone_session` copies `session_plan_items` (`repositories/training_sessions.py:858-859`) | SESSION §2, PLAN §5 |
| D11 | Analytics «0.5 тренировки» | equal per-block share (`training_analytics.py:361-375`) displayed by `formatShare` | SESSION §6 A2 |
| D12 | «pull_ups» / «user» / «block_a» next to «Подтягивания» (FD-19) | distribution groups by raw `Exercise.category/subcategory` slugs | WORKOUT §2, SESSION §6 A3–A4 |
| D13 | Minutes don’t reconcile; date edit erases duration | duration derived as `completed_at − performed_at` (1 min–6 h) and `completed_at = performed_at` for manual; date edit moves only `performed_at` (`repositories/training_sessions.py:784-787`); per-week flooring | SESSION §3, §6 A5 |
| D14 | Analytics ≠ Journal ≠ Profile totals | analytics include backfilled copies, Journal/Profile exclude them; legacy writes after backfill never reach v2 (`services/training_analytics.py:72`) | SESSION §6 A6, MIGRATION §4 |
| D15 | Course blocks nameless in Live/Journal (FD-16) | STEP blocks have no snapshot, `exercise_name=None` (`routes_v2.py:1586`), internal exercises hidden from library lookup | WORKOUT §2, §7 |
| D16 | Interval loses per-round reps (legacy «3 минуты» recorded them) | `ResolvedInterval` → only `completed_cycles` (`live_session.py:643-675`) | WORKOUT §3.4 |
| D17 | Rest ladders (180/120/60) flattened to one value | single `rest_seconds` per protocol | WORKOUT §3.5 |

## Accepted decisions (recorded, not re-opened)

Owner decisions already in force:

- **Premium trial = 7 days** (`TRIAL_DAYS = 7`), onboarding is a *minimum guarantee*: an ACTIVE
  entitlement is never shortened or downgraded, and no-op writes no history row
  (`app/services/subscription.py:36-65`).
- **«Подтягивания» program is free forever** via `programs.access_level = 'free'`.
- **`access_level` (catalogue property) ≠ subscription status (user entitlement)**; one decision
  path `ProgramAccessService` → `program_training_allowed`; unknown level fails closed.
- Crimpd 8.5.x is the functional UX reference; **future weeks visible and startable**.
- Main «Подтягивания» sessions need **two rest days between them** (exact day arithmetic: OD-2).

Architecture decisions made in Wave 0 (ADR-style, binding for Waves 1–4):

| ID | Decision | Where |
|---|---|---|
| AD-1 | Prescription is stored **set-explicit** (a list of set prescriptions per block). `sets × reps` is authoring shorthand only | WORKOUT §3 |
| AD-2 | WorkoutDefinitions are versioned by **immutable content-hashed versions**; every strength session stores a self-contained `PrescriptionSnapshot` **and** the version id | WORKOUT §5 |
| AD-3 | The main «Подтягивания» workout is **one WorkoutDefinition with two progression-sourced blocks** (A, B), not two plan rows of role exercises | WORKOUT §6, PLAN §2 |
| AD-4 | **One PlanItem = one workout occurrence.** `count_per_week` becomes a generation parameter, not a row attribute | PLAN §5 |
| AD-5 | Desired frequency (Program) is separate from valid placement (Plan + constraint check). Constraints are enforced **at start on the server**, displayed on the plan | PLAN §4 |
| AD-6 | **Server owns the engine.** Transitions are a pure function `advance(state, event, at)`; the client renders a projection of the same pure function; ONE deadline per phase, absolute UTC + server-time offset | LIVE §2 |
| AD-7 | Deterministic phases (prep, rest, timed work, interval) **auto-advance at the deadline**; only result entry waits for the user | LIVE §3 |
| AD-8 | **One TrainingSession entity** for planned live, direct live, manual existing, manual custom, external activity; `source` is explicit and set at creation | SESSION §2 |
| AD-9 | Analytics are a **pure derivation** over one canonical predicate of completed sessions; no fractional workout ever leaves the API | SESSION §6 |
| AD-10 | Migration is **expand → deterministic backfill → converge → dual-read → cutover**; legacy tables frozen, never deleted | MIGRATION |

## Owner decisions still open

See the short list in [PROGRAM_PLAN_V2.md §9](PROGRAM_PLAN_V2.md#9-owner-decisions-blocking).
Only those block implementation; everything else in this folder is decided.

## Implementation campaign

Waves, issues, dependencies, parallelization: [MIGRATION_V2.md §9](MIGRATION_V2.md#9-implementation-waves-and-parallelization).
