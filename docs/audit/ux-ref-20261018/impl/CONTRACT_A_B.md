# API contract A ↔ B (coordinator-owned; changes only through the coordinator)

Version 1 · base code SHA `e2ed40e5da46e8a2a743fd4a69f0f9e9b4d1d8e0` · campaign `campaign/ux-ref-20261018`.
A implements the backend side, B consumes it. B codes against this document with mocks/fixtures from the first checkpoint on;
A's real fields replace the mocks when A pushes. **Additive only**: no existing field is renamed, retyped or removed.
Facts, no prose: all Russian text lives in the frontend (B).

## 1. `GET /api/v2/plan` → `plan_items[]` (PlanItemResponse) — new fields

| field | type | meaning |
|---|---|---|
| `start_allowed` | `bool` | **single source for «Начать»**: true only if starting this row can succeed *now* for this user (access, spacing, state). The frontend shows «Начать» iff `start_allowed`. Default `false` for completed/missed/infeasible/too_early rows; `true` for ordinary custom/manual rows that are open. |
| `blocked_reason` | `"too_early" \| "infeasible" \| "completed" \| "missed" \| "no_access" \| null` | why `start_allowed` is false (null when allowed). Same vocabulary as the existing `state`. |
| `available_from` | `date \| null` | existing field; **must be correct for current and future weeks** (UX-02): the first local date on which the main slot may start given the last actual main session and the spacing rule (3 days, OD-2). |
| `session_variant` | `"A" \| "B" \| null` | which course session the row is (the same source as the Summary line «Следующая тренировка B»); null for non-course rows or when it cannot be projected. |
| `session_variant_basis` | `"actual" \| "projected" \| null` | `actual` = follows the progression cursor; `projected` = future row counted forward from the cursor. |
| `session_ordinal` | `int \| null` | 1-based position of the row among the course's main occurrences of this week (for the wording «занятие 2 из 3»). |

## 2. `ProgramInclusionResponse` — new field `schedule`

```json
"schedule": {
  "sessions_per_week": 3,
  "source": "catalogue",
  "is_legacy": true,
  "min_days_between_starts": 3,
  "weekly_capacity": 2
}
```
- `sessions_per_week` — what the plan **actually materialises** per open week for this inclusion (UX-32: 3 for a pre-V5.6 snapshot, 2 for a V5.6 one).
- `source` — `"snapshot"` (frozen slots) \| `"catalogue"` (snapshot has no slots; frequency from the programme catalogue).
- `is_legacy` — true when the inclusion is not a V5.6 inclusion (`snapshot.schedule` missing / older strategy).
- `min_days_between_starts` — spacing for the `main` group.
- `weekly_capacity` — how many main starts physically fit into a Mon–Sun week with that spacing, counted from a clean week (3-day spacing → 3 fits as Mon/Thu/Sun, but only if started exactly on time; A documents the formula in the tests). Lets the frontend say «не все занятия уместятся».
**No behaviour change for legacy inclusions**: `derive_slots` and convergence still produce 3 for them. The 3→2 transition is **not** implemented in this campaign.

## 3. `TrainingPlanResponse.week_summaries[]`
`planned/completed/infeasible/missed` must stay consistent with the row states of the same week (A adds a test: sum of row states == summary). No new field.

## 4. Electives — no API change
B uses the existing `GET /api/elective/plan` (`elective_allowed`, `elective_limit`, `entries_this_week`, `is_rest_day`, `ready_at`, `available_types`) and the existing `ElectiveScreen`. Free: no subscription gate (owner decision 2026-10-17).

## 5. Fixture shape that both sides use (owner-shaped legacy inclusion, UX-32)
A user with: `training_plans` row; `program_inclusions` row, program «Подтягивания» (catalogue `frequency = {sessions_per_week: 3}`), `snapshot` **without** `slots` and **without** `schedule`, `progression_strategy_type = "step"`, `program_items` = two items with `count_per_week = 3` and `day_of_week = null`; one **completed** main session in the current week linked to occurrence 1; plan week materialised → 3 `main` occurrences (1 done, 2 open). Expected UI: «1 из 3» + a visible explanation that this connection's schedule is 3 per week; rows that cannot be started say when they can.
A ships it as a pytest fixture/helper (`tests/helpers/legacy_inclusion.py` or equivalent); B reproduces the same shape in the E2E seed.

## 6. Change protocol
Need a field changed/added? Write `docs/audit/ux-ref-20261018/checkpoints/<worker>-contract-request.md`, push, and continue on the current contract; the coordinator answers in `CONTRACT_A_B.md` (new version). Never edit another worker's files.
