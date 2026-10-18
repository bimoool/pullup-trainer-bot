# UX-EDITOR — data contract (phase 1)

Branch `ux/editor`, base seam 6cc71d4 (code = main e2ed40e). Scope: UX-24, 12, 13, 25, 26, 28, 31 (+10/11 untouched except wording).
Out of scope: the 3→2 transition, 0.5 quantities (Q2: integers), hours totals (we do not invent durations; sessions only).
**Hand-computed dates below assume: today = Sun 18 Oct 2026, the user's TrainingPlan created in the week of Mon 5 Oct → calendar week 1 = 5 Oct, so today is in calendar week 2 (12–18 Oct); plannable window = calendar weeks 2..6 (`MAX_FUTURE_PLAN_WEEKS = 4`).**

## 1. What exists today (read from code)

* `custom_plans` (`app/db/models_program.py:466`): `workouts` JSONB `[workout_id,…]` (rotation order), `weeks` JSONB `[total_per_week,…]` (0 = explicit empty week), `repeat` `once|cycle`, `preferred_weekdays` JSONB hint, `start_week_number` (calendar week of week 1), `is_active`. **No per-workout quantity and no phase are stored anywhere.**
* Occurrences: `PlanConvergenceService._ensure_custom_occurrences` (`plan_convergence.py:451`) calls `custom_week_occurrences` (`plan_occurrence.py:427`): for a week it makes `weeks[offset]` rows, workout = `workouts[(rows_before + i) % N]` (a running counter through all earlier weeks), `occurrence_index = i+1`, `day_of_week` = i-th preferred weekday or `NULL`. Existing rows are matched **by `occurrence_index`** (removed rows keep their index). Rows exist only for calendar weeks `current..current+4`; later weeks are materialised when they enter the window.
* One `PlanItem` row = one occurrence (`source='custom_plan'`, `custom_plan_id`, `plan_week_id`, `origin_plan_week_id`, `day_of_week`, `scheduled_date`, `status open|rescheduled|removed`). Credit = `SessionPlanItem` link; `credited_plan_item_ids()`. Removal: `retire_open_custom_rows` (status `removed`, never touches credited or past weeks). Move: `PlanScheduleService.reschedule` (PATCH `/plan-items/{id}`; refuses credited/past-week/legacy rows; **does not refuse a past day inside the current week** — UX-31).
* API: `GET/POST /api/v2/custom-plans`, `POST …/{id}/deactivate` (`routes_v2_plan.py`), `GET /plan` returns `custom_plans`, plan-items `POST/PATCH/DELETE` (`routes_v2.py:1243+`). Create is Premium-gated (`_require_premium_feature`), deactivate is not.
* UI: `CustomPlanScreen` (checkbox list + text field «2 2 0 2», weekday hint chips), `AddToPlanScreen` (one manual row, current week, day or «Свободный пул»), `MovePlanItemScreen` (week + `DayPicker`), `DayPicker` («Свободный пул» label, l.42), `DashboardScreen` week view (rows: «Начать» in current week, «⋯» only in future weeks; «Свободный пул» heading l.1349).
* `PlanWeek.phase` (`base|rest|peak`, PG enum `mp_week_phase`) belongs to the **calendar** week and the course; it is not per custom plan. Last alembic head: `b5d8e1f3a6c9` (single head).

## 2. Data model — quantity per workout per week (+ phases)

**Why existing columns cannot hold it (proof by numbers).** The matrix is N workouts × W weeks with W ≤ 52; rows exist for ≤ 5 calendar weeks only (window), so quantities of week 6+ have nowhere to live except `custom_plans`. `weeks` (`list[int]`) holds one number per week: the 4-week example (a) needs 8 numbers (A 2/2/0/1, B 1/1/1/1) plus 4 phases; flattening into `weeks` is ambiguous with legacy rows (N=2,W=4 → len 4 and N=4,W=2 → 8… e.g. legacy `[2,2,0,2]` with 2 workouts is indistinguishable from a flat 2-week × 2-workout matrix). `preferred_weekdays` is a weekday hint (0..6) — overloading it would corrupt UX-25 hints. Making `weeks` polymorphic (dict) would crash every reader (`custom_week_count`, response `weeks: list[int]`, frontend `weeks.map`) and old code during a rolling deploy.

### CONTRACT REQUEST (coordinator decision needed before phase 2 code)
**R1 — one additive migration:** `custom_plans.spec JSONB NULL` (no default, no backfill, no index; table has no `*_archive_admin_reset` twin — the five twins are workouts/blocks/workout_sets/baselines/equipment_items, so the CLAUDE.md archive rule is not triggered). Down-revision = the then-current head (today `b5d8e1f3a6c9`); **WEB-AUTH also adds a migration → the coordinator must chain the two so one alembic head remains**; mine is small and can go first or last.
`spec = {"v": 2, "quantities": [[int per week] per entry of `workouts`, same order], "phases": ["base"|"rest"|"peak" per week]}`; `len(phases) == len(quantities[i]) == W`. `workouts`, `repeat`, `start_week_number`, `is_active` unchanged. **`weeks` stays and is kept equal to the per-week totals** (`weeks[w] = Σ_i quantities[i][w]`), so old readers, `GET /plan`, `CustomPlanResponse.weeks` and any old code during deploy keep working.
*Fallback if R1 is refused:* store the same JSON object inside `preferred_weekdays`' sibling is impossible; the only no-migration route is a polymorphic `weeks` (dict with key `v`) and an updated reader layer — I rate it unsafe (old code crashes in convergence) and would implement it only on explicit instruction. Default recommendation: **approve R1**.
All access goes through one accessor `custom_plan_spec(custom_plan) -> PlanSpec` (domain dataclass, `app/domain/plan_spec.py`, no ORM) so the storage place is a single function.

**Phases.** Only existing `WeekPhase` values (База / Отдых / Пик); the reference's «Build» needs a PG-enum migration — not done (documented difference). A week whose total is 0 is shown «Неделя отдыха по плану» regardless of phase (UX-12). Custom-plan phase is shown only inside the editor/week header of that plan; `PlanWeek.phase` is not touched.

**Conversion of existing plans (lazy, in memory, nothing changes until the user edits).** `spec IS NULL` ⇒ derive:
`quantities[i][w] = #{k : (before(w)+k) mod N == i, 0 ≤ k < weeks[w]}`, `phases = all base`. Persist (and refresh `weeks`) only on the first editor mutation. Cycle plans: matrix repeat equals legacy only if `Σweeks mod N == 0`; otherwise take the smallest k ≤ N with `k·Σweeks mod N == 0` and unroll k·W weeks (if k·W > 52: unroll to 52 and set `repeat='once'`, shown in the editor as a notice). Duplicated ids in `workouts` stay separate rows (position-keyed); new additions must be unique.
**Materialisation switches from index-matching to count reconciliation** (needed because legacy index order ≠ workout order when N is odd): for each calendar week in the window, for each workout, `have` = non-removed rows (open+credited) of that workout in that week; shortfall → create rows with `occurrence_index = max(existing incl. removed)+1`, `day_of_week=NULL` (hint rule unchanged); surplus → retire open uncredited rows, unplaced first, then latest day; credited rows are never touched. Legacy plans therefore yield **zero mutations** at conversion (example b).

**History untouched.** No change to sessions, `SessionPlanItem`, credits, past weeks, `completed_main_sessions`, progression, `derive_slots`. Removed rows keep their ids.

## 3. API (additive, `/api/v2`, new code in `app/web/routes_v2_plan.py` + `schemas_v2.py` custom hunks)

All mutations: plan lock → update spec + derived `weeks` → reconcile affected window weeks (the same `_ensure_custom_occurrences`) → commit → return the editor view. Premium gate as for create on quantity/phase/insert/add; **not** gated: delete week, remove workout, unplace (as deactivate). Foreign/unknown id → 404.

| Method / path | Body | Notes |
|---|---|---|
| `GET /custom-plans/{id}/editor` | – | full matrix view (below) |
| `PATCH /custom-plans/{id}/weeks/{index}/quantities` | `{"quantities": {"101": 2, "102": 1}}` | week index 1-based; ints 0..14, week total ≤ 14; ≥ number of credited rows of that workout in that week else 422 `below_done` |
| `PATCH /custom-plans/{id}/weeks/{index}` | `{"phase": "rest"}` | phase only |
| `POST /custom-plans/{id}/weeks` | `{"after_index": 2}` | inserts an empty base week; `after_index ∈ 0..W` |
| `DELETE /custom-plans/{id}/weeks/{index}` | – | |
| `POST /custom-plans/{id}/workouts` | `{"workout_id": 103}` | adds a row of zeros (same attachability check as create); also the entry for «Добавить в план» |
| `DELETE /custom-plans/{id}/workouts/{workout_id}` | – | open rows retired, credited kept; response lists counts |
| `GET /custom-plans/{id}/weeks/{index}/schedule` | – | schedule view model |
| `POST …/weeks/{index}/place` | `{"workout_id":101,"day_of_week":1}` | takes one unplaced row of that workout/week → day; 422 `quota_exhausted` («все занятия размещены»), 422 `past_day` |
| `POST …/weeks/{index}/unplace` | `{"workout_id":101,"day_of_week":1}` | one row of that workout on that day → unplaced (highest occurrence_index); 422 if credited |
| `POST /custom-plans` (existing) | + optional `quantities: int[][]`, `phases: string[]` | when given, `weeks` is ignored/derived and `workout_ids` must be unique; old body unchanged |
| `PATCH /plan-items/{id}` (existing) | – | adds `past_day` 422 (day earlier than today in the current week, UX-31); unchanged otherwise |

**Week operation rules (error `code` in `detail`, nothing changes on error).**
* Past weeks and the current week: read-only for insert/delete/before-insert (`week_not_editable`, `reason: past|current`). Quantities and phase of the **current** week are editable (floors: credited count), past weeks are not.
* Insert at position `pos = after_index+1`: calendar week `start+pos-1` must be > current, else `week_not_editable`. All rows in weeks ≥ pos shift +1 calendar week (open rows are *moved*, keeping day, identity and `occurrence_index`; if the target is beyond the window they are retired and re-created when the window reaches them). If any **credited** row lies in a shifted week → 422 `week_has_done_sessions` (credited rows can't move; user must act on the later weeks first).
* Delete week `index`: calendar week must be > current and contain **zero credited rows**, else 422 `week_not_editable` / `week_has_done_sessions`. Open rows of that week are retired (`removed`, not hard-deleted), later weeks shift −1 (moved as above), plan gets one week shorter. UI confirmation names what is lost (count + workouts).
* Remove workout: its open rows in current/future weeks are retired, credited ones stay (counted in the history), column of quantities dropped; last workout cannot be removed (use «Остановить план»).

**Editor view response (excerpt).**
```json
{ "id": 7, "display_name": "Мой план", "repeat": "once", "start_week_number": 2,
  "current_week_index": 1, "converted": true, "notice": null,
  "workouts": [{"workout_id": 101, "title": "A", "live": true}, {"workout_id": 102, "title": "B", "live": true}],
  "weeks": [
    {"index": 1, "week_number": 2, "start_date": "2026-10-12", "state": "current", "phase": "base",
     "total": 3, "quantities": {"101": 2, "102": 1}, "done": {"101": 1, "102": 0}, "placed": 1},
    {"index": 2, "week_number": 3, "start_date": "2026-10-19", "state": "future", "phase": "base",
     "total": 3, "quantities": {"101": 2, "102": 1}, "done": {}, "placed": 0} ] }
```
`state ∈ past|current|future`; `converted=false` means the plan is still legacy (spec NULL; the response is derived, nothing was written). Schedule view: `{"index":1,"week_number":2,"days":[{"day":0,"date":"2026-10-12","state":"past|today|future","total":0}, …7], "workouts":[{"workout_id":101,"title":"A","quantity":2,"placed_by_day":[0,2,0,0,0,0,0],"remaining":0,"items":[{"plan_item_id":..,"day":1,"done":false,"missed":true}]}]}` — `missed` = placed on a past day, not credited («пропущено»). Unplaced bucket name in all UI: **«Без дня»** (replaces «Свободный пул», UX-13; reference calls it «THIS WEEK», which would be wrong for a future week).

## 4. Hand-computed examples (all become tests)

**(a) Quantities and totals.** 4-week plan, A=101: 2/2/0/1, B=102: 1/1/1/1. Weekly totals: W1 2+1=3, W2 2+1=3, W3 0+1=1, W4 1+1=2; `weeks` = [3,3,1,2]; plan total 9 (A 5, B 4). Calendar W1..W4 = weeks 2..5 (12 Oct, 19 Oct, 26 Oct, 2 Nov). Materialised rows now (window 2..6): 3 + 3 + 1 + 2 = 9 rows, all `day NULL`, `occurrence_index` 1..3, 1..3, 1, 1..2.

**(b) Legacy conversion.** `workouts=[101,102]`, `weeks=[2,2,0,2]`, once, start 2, no hints. Rotation counter: W1 before=0 → idx1=101, idx2=102; W2 before=2 → 101,102; W3 empty; W4 before=4 → 101,102. Derived `quantities` A=[1,1,0,1], B=[1,1,0,1], phases base×4, `weeks` totals [2,2,0,2] (equal). Rows today (current week = cal 2, offset 0): idx1→101, idx2→102 (2 rows); cal 3: 2 rows; cal 4: 0; cal 5: 2; cal 6: outside plan → 6 rows total, **reconcile mutations = 0** before and after. Odd-N check: `workouts=[101,102,103]`, `weeks=[2,2,2]` → W1 101,102; W2 103,101; W3 102,103 ⇒ 101=[1,1,0], 102=[1,0,1], 103=[0,1,1]; legacy W2 rows are idx1=103, idx2=101 while the matrix orders 101 first — count reconciliation sees 1+1 = match, 0 mutations (index matching would have been wrong). Cycle check: N=2, `weeks=[3]`, cycle: Σ=3, 3 mod 2 ≠ 0 → k=2 → 2 weeks: legacy W1 before=0: 101,102,101; W2 before=3: 102,101,102 ⇒ 101=[2,1], 102=[1,2], totals [3,3] ✓.

**(c) Insert a week after week 2** on plan (a), today in W1 (cal 2), one A session already credited in W1. `pos=3` → cal 4 > 2: allowed. New matrix A=[2,2,0,0,1], B=[1,1,0,1,1], phases [base,base,base,base,base] with the new W3 empty; totals [3,3,0,1,2] (sum 9, unchanged). Rows: before cal2:3, cal3:3, cal4:1(B), cal5:2 = 9. Move: cal5 rows → cal6, then cal4 row (B, keeps its day, e.g. Wed) → cal5. After: cal2:3 (incl. the credited A, untouched), cal3:3, cal4:0, cal5:1(B), cal6:2 = 9. Insert after week 0 (before W1) or after week 1 when cal 3 ≤ current → `week_not_editable`. If the credited A had been in W3 (cal 4, early session) → 422 `week_has_done_sessions`, state unchanged.

**(d) Delete a week.**
 * Future week without done: delete W3 of (a): A=[2,2,1], B=[1,1,1], totals [3,3,2] (was [3,3,1,2]); the B row of cal 4 is retired (status removed), cal5 rows (A,B) move to cal4; rows after: 3+3+2 = 8 = 9−1; plan ends cal 4. Confirmation text: «Будет убрано занятий: 1 (B). Следующие недели сдвинутся на неделю назад».
 * Week with 1 done + 1 open (A=2 in W2 = cal 3, one credited in advance): delete → 422 `week_has_done_sessions` (done=1, open=1), **nothing changes**. Allowed alternative: set A in W2 to 1 (floor = 1 done): open A row retired, done row kept → A=[2,1,0,1], totals [3,2,1,2]; setting A to 0 → 422 `below_done` (min 1).
 * Delete W1 (current week) → 422 `week_not_editable` reason `current`.

**(e) Same workout twice in one day.** Week W1 of (a), A quantity 2. Schedule: place(A, Tue) → `placed_by_day=[0,1,0…]`, day total Tue=1, remaining 1; place(A, Tue) again → Tue=2, remaining 0, label «все занятия размещены», two rows with `day_of_week=1`, `occurrence_index` 1 and 2. A third place → 422 `quota_exhausted`. Per-day totals row (A×2 on Tue + B×1 on Thu): [0,2,0,1,0,0,0]. Move one A Tue→Thu via unplace+place (or PATCH): Tue 1, Thu 2 (A1 + B1), A remaining 0. In the current week with today = Sun 18 Oct (day 6): place on Mon..Sat → 422 `past_day`; Sun allowed; rows placed on past days and not done show «пропущено».

## 5. Acceptance tests (names → exact expected values)

Backend (`tests/test_domain/test_plan_spec.py`, `tests/test_services/test_custom_plan_editor.py`, `tests/test_web/test_custom_plan_editor.py`, real Postgres for services/web):
* `test_totals_per_week_example_a` → weeks `[3,3,1,2]`, rows 9, indexes as in (a).
* `test_legacy_conversion_two_workouts_is_lossless` → A=[1,1,0,1], B=[1,1,0,1], totals `[2,2,0,2]`, reconcile creates 0 / retires 0.
* `test_legacy_conversion_odd_rotation` → 101=[1,1,0], 102=[1,0,1], 103=[0,1,1]; 0 mutations.
* `test_legacy_cycle_unroll` → 101=[2,1], 102=[1,2].
* `test_insert_week_shifts_open_rows_and_keeps_credited` → totals `[3,3,0,1,2]`, row counts per calendar week `3,3,0,1,2`, credited row id unchanged, the B row keeps its day.
* `test_insert_week_refused_when_shifted_week_has_done` and `test_insert_before_current_refused` → 422 codes, DB unchanged.
* `test_delete_future_week_retires_and_shifts` → A=[2,2,1], B=[1,1,1], rows 8, one `removed`.
* `test_delete_week_with_done_refused` and `test_quantity_below_done_refused` → 422 `week_has_done_sessions` / `below_done`; lowering to 1 keeps done + retires open.
* `test_place_same_day_twice_and_quota` → Tue total 2, remaining 0, third place 422 `quota_exhausted`; `test_place_past_day_refused` (today Sun: Mon → `past_day`); `test_move_row_to_past_day_refused` (PATCH, UX-31).
* `test_history_untouched_after_edits` → credited rows, sessions, `completed_main_sessions` identical before/after a sequence of edits.
* Revert-proof: for count reconciliation (odd rotation), for the credited-row guards and for `past_day` I will revert each fix once and show the test failing (noted in the checkpoint).
Frontend: `node --test tests/*.test.ts` for the pure helpers (`weekTotals`, `remainingToPlace`, `dayTotals`).
E2E `scenarios/ux-editor-*.spec.ts` (seed ids 941000–941099, additive scenario functions in `scripts/e2e_seed.py`): create 4-week plan → totals row «3 · 3 · 1 · 2»; ×2 on one day shows «×2» and day total 2; move across weeks; remove with in-app confirm (cancel changes nothing); reload identical; aged legacy `[2,2,0,2]` plan: visible plan identical before/after opening the editor and after the first edit of a different week.

**UI states.** Editor: empty plan (no workouts) → «Добавьте тренировки в план» + button; week with total 0 → «Неделя отдыха по плану»; week phase chip База/Отдых/Пик; stepper −/+ (min = done, max 14, week total ≤ 14, disabled at limits with a hint); past weeks greyed, steppers disabled, labelled «Прошла»; `converted=false` plans open normally (no banner). Schedule: header «Неделя N · 12–18 окт», day circles Пн..Вс with per-day total, per workout pill «осталось разместить N» → «все занятия размещены» when 0 (also shown instead of the silent ignore after a tap), stepper +/− per day (not tap-cycling), past days disabled with label, missed rows «пропущено». Confirmations (in-app sheets, never `window.confirm`): delete week, remove workout, unplace/remove session — each names what is lost and has visible «Отмена». Row actions: the same «⋯» (Перенести / Редактировать тренировку / Убрать из плана) on every row of an editable week including the current one; Move sheet gets a visible «Отмена» and no past days (UX-31). Progress presentation (UX-26): done state «1/1 ✓» on the card and week header «выполнено X из Y» per phase — presentation only, credit rule unchanged (J7).

## 6. Risks and phase-2 checkpoint split

Risks: (1) R1 migration needs a decision and chaining with WEB-AUTH's; (2) count reconciliation changes how existing open rows are matched — covered by tests (b) and the aged-seed before/after check; (3) moving rows across calendar weeks touches `plan_week_id/origin_plan_week_id/scheduled_date` — must preserve ids; (4) `routes_v2.py`/`schemas_v2.py` hunks overlap other workers (A/C) — my code goes into `routes_v2_plan.py` and a custom block of `schemas_v2.py`; (5) `DashboardScreen.tsx` is 1486 lines — editor/schedule are new files, Dashboard only gets entry points and the shared row-action change; (6) no live Telegram verification; (7) «Build» phase and fractional quantities deliberately absent.
Split: **P2-1** domain `plan_spec.py` + conversion + reconcile + tests (b),(a); **P2-2** migration (if approved) + services/endpoints for quantities/phases/workouts/insert/delete + tests (c),(d); **P2-3** schedule endpoints + `past_day` + tests (e); **P2-4** frontend editor screen, entry points (CustomPlanScreen replaced, AddToPlan link), rename «Без дня»; **P2-5** schedule screen, confirmations, row actions, UX-26 presentation; **P2-6** seed scenarios + e2e specs + aged-conversion check + revert-proof notes.
