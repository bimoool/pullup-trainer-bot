# PROGRAM_PLAN_V2 — Program, progression input, constraints, Plan, access

Index: [README.md](README.md). Workout shape: [WORKOUT_DOMAIN_V2.md](WORKOUT_DOMAIN_V2.md).

**Program** = *what* to train and *how it progresses* (content + rules, user-independent).
**ProgramInclusion** = a user's enrolment (frozen snapshot + progression state).
**Plan** = *concrete occurrences* in the user's calendar weeks (PlanItems).

## 1. Program

```
Program
  id, display_name, category_id, access_level (free | premium), structure_type
  slots: ProgramSlot[]            ordered
  progression_strategy_id, config (constants, schema_versioned)
  frequency: { sessions_per_week: int, per_slot overrides }     DESIRED volume, not placement
  constraints: SchedulingConstraint[]                           (§4)
  assessment: { protocol_id, required_before_first_session: bool, validity_days } | null

ProgramSlot
  key              stable ("main", "elective_w", ...)
  workout_definition_id
  role             main | optional | assessment
  spacing_group    str | null      sessions in the same group obey that group's min-rest
  repeat           every_session | rotation(order) | once
  counts_toward_progression bool   (main: true; optional: false)
```

«Подтягивания» (system, `access_level=free`): slot `main` → WorkoutDefinition «Подтягивания»
(AD-3; one occurrence = blocks A+B), `sessions_per_week = 3`, spacing group `main` with
`min_days_between_starts` (OD-2), assessment «Максимум подтягиваний» required before the first
main session. Electives are `optional` slots outside the `main` spacing group (legacy rotation and
limits unchanged).

## 2. ProgramInclusion (enrolment state)

Kept from today (`program_inclusions`): `snapshot` (frozen program content at enrolment),
`progression_state` (live), `initial_progression_state` (frozen), `is_active`, `expires_at`. Added:

- `progression_state_rev` int (+1 per applied progression; recorded in session snapshot provenance)
- `sequence_cursor` (next slot occurrence number; progression is **sequence-based**, not calendar-based)
- `baseline_assessment_result_id` (the assessment used to initialise state; §3)

Completion state: `completed_main_sessions`, `last_main_session_at` (derived from sessions,
cached), `status: active | paused | completed | removed`. Removing/re-adding a course **resumes**
the previous inclusion state unless the user explicitly restarts (fixes DV-05 reset; restart is a
separate explicit action).

## 3. Assessment → initial prescription (traced; formula is an owner decision)

**Trace at `4298f8b`, fresh user, assessment max = 8:**

| Era | Path | Result | Why |
|---|---|---|---|
| Program era (Mini App, live today) | `POST /api/v2/program-inclusions {program_id}` (`webapp-frontend/src/apiV2.ts:811`) → `_build_initial_progression_state` (`app/services/program_inclusion.py:46-99`) | **10 × 3, BODYWEIGHT** | `target_a = config.block_a.base_target` (=10, seed `a4c8e1f7b2d9…py:52`; fallback `VOLUME_BLOCK.base_target`, `app/domain/constants.py:90`); `work_sets_a = 3`; equipment hard-coded BODYWEIGHT (`:82,:91`). **The baseline is never read** (docstring `:53-57`). Any max (3, 8, 20) gives 10 × 3. |
| Bot era (legacy) | `suggest_starting_equipment(8)` + `initial_volume_target(8)` (`app/domain/progression.py:347-396`) | **10 × 3 on a BAND** (+ max set) | `8 ≤ 10` → band chosen to make ~10 reps reachable; `ceil(0.75 × max)` only when `max > 10`. Documented only in docstrings («Часть 10, пакет #2, п.14»); not in `docs/progression.md`. |

Conclusion: **there is no explicit rule for the program era.** «10» is the default
`base_target` applied because the baseline is not wired in; the bot era's safety condition (a
band) was dropped. For max = 8, 3 × 10 bodyweight = 30 reps ≥ 3.75 × max per block, each set
above the user's max — **unsafe/undefined**. Also wrong upward: max = 20 → 10 instead of
`ceil(0.75 × 20) = 15`. Already logged as FD-17.

Contract (mechanism, decided): `initial_state = InitialPrescriptionRule(program.config,
assessment_result)` — a pure, versioned function; the inclusion records which rule version and
which assessment result produced it. Enrolment into a program with `required_before_first_session`
and no valid assessment yields state `awaiting_assessment`; the plan shows «Сначала тест на
максимум», and the main slot is not startable until the assessment is logged.
The **numbers** of the rule are OD-1.

## 4. Scheduling constraints (min rest days)

```
SchedulingConstraint
  spacing_group           "main"
  min_days_between_starts int     calendar days in the user's timezone between local start dates
```

`available_from(group) = local_date(last completed session in group) + min_days_between_starts`.

Today: `MIN_REST_DAYS = 2` with `days = current − last; days < 2 → TOO_EARLY`
(`app/domain/rules.py:30-52`) — i.e. **Mon → Wed allowed (one full rest day)**. Enforced only in
legacy bot/`/api/workout/plan` and as an advisory dashboard status; **not** on `POST
/api/v2/sessions/live` (D6). `config.min_rest_days` is stored but never read.

The owner rule «2 REST DAYS between MAIN sessions» read literally is `min_days_between_starts = 3`
(Mon → Thu). Numbers for both (decision OD-2):

| Value | Allowed after Mon | Mon/Wed/Fri valid? | Max in one Mon–Sun week | Sustained rate |
|---|---|---|---|---|
| 2 (code today) | Wed | yes | 4 (Mon, Wed, Fri, Sun) | 3.5 / week |
| 3 (literal) | Thu | **no** | 3 (Mon, Thu, Sun) only if the previous week ended ≤ Fri | 2.33 / week |

Rules (decided, independent of the value):

- **K1** The server rejects `start` of a `main` occurrence before `available_from` with
  `too_early{available_from}` (LIVE §7) — on every path (v2 live, legacy, bot), admins bypass as
  today (`docs/payments.md`).
- **K2** Desired frequency ≠ placement. For each week the plan computes
  `feasible_remaining = count of dates d in [max(today, available_from), week_end]` stepping by
  `min_days_between_starts`. Occurrences beyond `feasible_remaining` are shown as
  **«не успеть на этой неделе»** (state `infeasible`), not as debt and not as missed.
  Example (value 3): today Wed, last main Mon → available Thu → Thu, Sun → feasible 2 of 3.
- **K3** Manual logging (post-factum) of a main session is allowed even if it violates spacing
  (it already happened); it is flagged `spacing_violation=true` for progression to see.
- **K4** Optional and custom workouts are not in the `main` group unless their program says so.

## 5. Plan, PlanWeek, PlanItem, completion credit

```
TrainingPlan  (one per user; unchanged)
PlanWeek      week_number, start_date (Monday, user tz), phase           (unchanged)
PlanItem      ONE occurrence of ONE workout (AD-4)
  id, plan_week_id NOT NULL, source: program | custom_plan | manual
  program_inclusion_id | custom_plan_id | null
  program_slot_key | null, occurrence_index (1..n within week & slot)
  workout_definition_id NOT NULL
  scheduled_date | null           optional calendar placement (weekday is metadata, not volume)
  status (stored): open | rescheduled | removed
  derived state: completed | missed | infeasible | available | too_early | awaiting_assessment
```

- **PL1** Volume = number of PlanItems. «3 из 3» counts occurrences, never `count_per_week`.
- **PL2** Completion credit: a session credits **at most one** PlanItem, only through an explicit
  `training_sessions.plan_item_id` chosen at start (from the plan) or at manual logging (user
  picks the occurrence). A session never credits by matching exercises or weeks.
- **PL3** Direct start from Workout Detail (`direct_live`) **never** credits the plan (J7).
  Clone never copies the plan link (D10).
- **PL4** A credited PlanItem is `completed` regardless of the session's week (starting a future
  week's item early credits that item; J12).
- **PL5** `missed` is derived: week ended, item open and not infeasible. No carry-over is
  generated (Crimpd behaviour); progression is sequence-based so the next main occurrence just
  continues the sequence.
- **PL6** Rescheduling = move to another week and/or date, any source (course items too). Moves
  are validated against K2 for display; K1 still decides at start.
- **PL7** Course occurrences for future weeks inside the window (`MAX_FUTURE_PLAN_WEEKS = 4`) are
  materialised by one idempotent `converge_user_plan(user, today)` (recovery audit T2); generation
  never writes on GET outside that function.
- **PL8** A **credited** PlanItem (referenced by any session: `training_sessions.plan_item_id` or the
  legacy M2M) is never deleted, soft-removed or re-pointed by a user action. An explicit «Убрать из
  плана» of it → `422 {code: credited_plan_item}`; deleting the workout or stopping its plan leaves it
  (and its credit) exactly as it was.
- **PL9** Removing an uncredited **custom-plan** occurrence is a soft removal (`status = removed`): the
  row keeps its identity, so convergence never regenerates it. Program occurrences are not removable one
  by one (the course is removed as a whole, §2); an uncredited **manual** row is hard-deleted (nothing
  regenerates it).
- **PL10** Rows of a removed course (`is_active = false`) that are uncredited and in the current or a
  future week are not part of the actionable plan: `GET /plan` omits them (no `available`, not in
  «N из M»); the DB rows stay (re-adding the course resumes them). Credited rows and past weeks stay
  visible as history.

## 6. Future weeks

**Visible and startable.** `_reject_future_week_course_item` (`app/services/live_session.py:297-307`)
is removed (D8). The only gates at start are access (§8), K1 spacing and assessment.

## 7. Custom workouts and per-week volume

```
CustomPlan (user-owned)
  id, user_id, display_name, start_week_number
  workouts: [{workout_definition_id, order}]      rotation pool
  weeks: [{week_offset: 0.., count: 0..14}]       TRUE per-week volume
  repeat: once | cycle
  preferred_weekdays: int[] | null                optional placement hint
```

**Stopping a custom plan** (`POST /api/v2/custom-plans/{id}/deactivate`, owner only, else 404):
`is_active = false` — an inactive custom plan never materialises new occurrences; its uncredited
current/future occurrences are soft-removed (PL9); credited occurrences, past weeks and sessions are
unchanged; a repeated call has no further effect. There is no re-activation in this wave.

Example W1=2, W2=2, W3=0, W4=2, W5=2, W6=0 → weeks with 2, 2, 0, 2, 2, 0 PlanItems; a zero week
is a valid, explicit value (today `count_per_week` is `ge=1`, `app/web/schemas_v2.py:506`, so 0 is
inexpressible). Workouts are assigned by rotation. Manual one-off PlanItems remain (`source =
manual`) for “add this workout to this week”.

## 8. Access (preserved; not redesigned)

Accepted decisions are listed in [README.md](README.md#accepted-decisions-recorded-not-re-opened).
Contract points for the new model:

- **AC1** Access gate is evaluated at *start* via `ProgramAccessService` on the PlanItem's program;
  a PlanItem of a `free` program is always startable access-wise.
- **AC2** Onboarding/assessment never writes subscription state except `start_trial`'s minimum
  guarantee; no v2 migration touches `users.subscription_*` or `subscriptions` (MIGRATION §7).
- **AC3** Custom plans and direct workouts are not gated (current behaviour) until OD-4.

## 9. Owner decisions (blocking)

| ID | Question | Blocks | Options with numbers |
|---|---|---|---|
| **OD-1** | Initial «Подтягивания» prescription from assessment max. Max = 8 gives 10 × 3 bodyweight today because the baseline is ignored (§3). | Wave 1 progression init (J1, J2) | (a) bot rule restored: max ≤ 10 → 10 × 3 **on a band** sized for ~10 (needs band selection in Mini App onboarding); max > 10 → `ceil(0.75·max)` × 3 bodyweight. (b) `ceil(0.75·max)` bodyweight for all: 8 → 6 × 3, 3 → 3 × 3, 20 → 15 × 3. (c) other explicit table. |
| **OD-2** | «2 rest days» = `min_days_between_starts` **2** (Mon→Wed, today's code) or **3** (Mon→Thu)? | Wave 1 K1/K2 value (mechanism proceeds) | **Resolved 2026-10-08: 3** — two FULL rest days (Mon → Thu); see §10 |
| **OD-3** | Main workout blocks keep the trailing **max set** (A: 3 × 10 + max; B: 4 × 3 + max) as in legacy? Current progression formula needs it. | Wave 1 resolver, J4 | yes (legacy parity) / no (then a new progression input must be specified) |
| **OD-4** | Free vs Premium for everything outside the free «Подтягивания» program (custom plans, system ready workouts, electives, Journal/Analytics/export) and «one trial per account» vs admin-reset QA re-trial | Nothing in Waves 1–3 (current behaviour kept); needed before any new paywall | — |

## 10. Implementation notes (Wave 1b, #304)

Where the contract left a choice open, Wave 1b decided as follows (code: `app/domain/plan_occurrence.py`,
`app/services/plan_convergence.py`, `app/services/plan_spacing.py`, `app/services/plan_view.py`, migration
`d8a3c6f1e2b4`). None changes a rule above.

1. **OD-2 resolved by the owner (2026-10-08):** two FULL rest days → `min_days_between_starts = 3`. Read source:
   `programs.constraints` (seeded for «Подтягивания»: `[{spacing_group: main, min_days_between_starts: 3}]`) of the
   user's active inclusion, else the catalogue «Подтягивания», else `settings.main_min_days_between_starts` (3).
   Constraints are a live catalogue property (like `access_level`), not frozen in the inclusion snapshot.
   `config.min_rest_days` (old «Mon → Wed» meaning) is left untouched and is not read.
2. **Last MAIN start** = max of legacy `workouts` (completed) and completed v2 sessions that credit a `main`
   occurrence or contain a STEP role block with ≥ 1 logged set (an empty abandoned start does not move rest).
   Local dates in the user's timezone.
3. **K1 error shape:** v2 live → `409 {code: "too_early", available_from: "YYYY-MM-DD", message}`; legacy
   `GET /api/workout/plan` / `/api/dashboard` / `GET /api/v2/dashboard/status` → `status: "too_early"` +
   `available_from`; bot → the existing «Рано…» text with the date (midnight of `available_from`, user tz).
   Admin bypass unchanged (`settings.is_admin`).
4. **Slots.** Frozen into the inclusion snapshot at enrolment (`snapshot.slots`). Legacy snapshots derive slots
   from `program_items`: items with the same `day_of_week` (NULL = pool) form ONE slot (one occurrence executes
   all of them — the old card grouped and started them together); the group containing STEP roles is `main`
   (spacing group `main`, counts toward progression). The `main` slot has no WorkoutDefinition yet
   (`workout_definition_id = NULL`): its occurrence resolves blocks A + B from the inclusion's role snapshot with
   today's numbers — the main WD and prescription numbers are #305.
5. **Occurrence identity** = `(origin_plan_week_id, program_inclusion_id | custom_plan_id, program_slot_key,
   occurrence_index)` (partial unique indexes). `plan_week_id` / `day_of_week` / `scheduled_date` are placement
   and may change (PL6, `status = rescheduled`). `scheduled_date = week start + day_of_week`.
6. **Volume** = rows: the program materialises exactly `sessions_per_week` occurrences per open week (desired
   volume); placement feasibility is derived on read (K2) — infeasible occurrences stay as rows with state
   `infeasible`, never silently dropped and never placed in violation of rest. Projection chains across weeks
   (`max(today, available_from)`, then `+ min_days`); a `scheduled_date` is honoured if not earlier than the chain.
7. **Credit.** `training_sessions.plan_item_id`, set only at live start from the plan (one occurrence per start;
   several → 422). An already-credited occurrence starts again without credit. Old-form rows that convergence
   has not expanded yet (pre-#304 clients/data) credit the first requested row. Direct start and clone never
   credit. No DB uniqueness on `plan_item_id` (legacy single-link backfill can map several historical sessions to
   one aggregate row); "one session → one item" is structural (single column).
8. **`converge_user_plan`** is the only writer of plan structure (PL7). Past weeks: aggregates get
   `legacy_aggregate = true` only. Current/future weeks: course aggregates → `status = removed` +
   `legacy_aggregate` (never deleted — M2M history points at them) **only together with their replacement
   occurrences** — rows of a course that is removed, non-recurring or has no materializable slot stay exactly as
   they were (startable old-form rows) — and k sessions linked in that week → k
   occurrences (`performed_at` order; a session already crediting another occurrence is never moved); manual
   rows with `count_per_week = N` → N occurrences (the row itself is #1); custom plans → their week volume.
   Inclusion cache: `status` / `sequence_cursor` only from NULL; `completed_main_sessions` /
   `last_main_session_at` derived. It never enrols, never re-creates an inclusion, never touches
   `started_at` / `progression_state` / `initial_progression_state` / subscription.
9. **Resume (§2).** Re-adding a removed course reactivates the previous inclusion (`is_active`, `status`,
   `expires_at = NULL`); `restart: true` creates a new one. `progression_state_rev` +1 per applied progression;
   `sequence_cursor` +1 when a credited main occurrence completes with progression.
10. **Removal and concurrency (independent review B1/B3/C1).** `app/services/plan_removal.py` applies PL8–PL10 for
    «Убрать из плана», workout deletion and «Остановить план». Before reading credit it takes the user's live-start
    advisory lock (`lock_user_starts`, the same lock a crediting start holds), then the plan row lock (`lock_plan`, the
    lock `converge_user_plan` holds) — a start and a removal of the same occurrence, or a removal/stop and a convergence,
    serialise; lock order advisory → plan, no cycle. No schema change (existing `status`, `is_active`, `plan_item_id`).
11. **Not in this wave:** `awaiting_assessment` (assessment stored in `programs.assessment`, not enforced — #305 with
    OD-1), K3 `spacing_violation` on post-factum logging (#307), occurrence `week_phase` (always `base`).

