# ACCEPTANCE_JOURNEYS_V2 — executable definition of done

Index: [README.md](README.md). Each journey asserts **observable product behaviour** (what the
user sees and what the persisted history/analytics say), never just status codes. Layers:
**D** pure domain (pytest, no DB) · **S** service on real Postgres · **W** API (`tests/test_web/`) ·
**E** Playwright E2E (`webapp-frontend/e2e/`) · **R** real iPhone (`docs/IPHONE_QA_CHECKLIST.md`).
Every journey runs on a **fresh** profile and, where marked ⟳, also on an **aged** profile
(MIGRATION §8). A test is accepted only if reverting the fix makes it fail (`docs/testing.md`).

| ID | Journey | Layers | Must observe |
|---|---|---|---|
| **J1** | Fresh user → onboarding → free «Подтягивания» → plan → live → Journal → Analytics → reopen | S W E R | Trial = 7 days; «Подтягивания» startable without Premium; assessment logged → initial prescription per OD-1 (exact numbers from the decision); plan week shows the main occurrence with names (no slugs); live runs Block A then B with the exact set counts of J4; Journal card titled «Подтягивания» with both blocks named; Analytics total = 1 (integer), category «Подтягивания» = 1, minutes = measured duration rounded; app reopen shows the same state |
| **J2** ⟳ | Same as J1 on aged/migrated users (backfill-era 19.09, legacy + v2 history, expired, payer) | S W E | After `converge_user_domain_v2`: same derived state as a fresh user with the same history; existing history count unchanged; totals equal across Journal, Profile, Analytics; payer's `subscription_expires_at` unchanged; apply-again = 0 changes |
| **J3** | W-ladder exact prescription | D W E | Detail/plan/pre-screen show «5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5»; live shows 17 sets with targets in that order and 10 s rests; persisted 17 `SetTarget` with those targets; Journal shows the sequence; never «17 × 3» |
| **J4** | Course Block B «4 × 3» exact execution and persistence for the legacy program version. [V5.6](PULLUPS_V5_6.md) governs new inclusions and has its own golden examples for M = 0/10/25/50. | D S E | Block B displays four working sets with a target of 3 and one explicit max set. The live counter reaches «5/5», and the database stores five `SetTarget` and five `SetLog` rows, with `is_max_set` on the fifth only. The [legacy STEP rule](PROGRAM_PLAN_V2.md#11-implementation-notes-wave-1c-305) uses both working repetitions and the max. At target 3 and max 6, four results of 3 lead to target 4. Four results of 2 lead to target 3. |
| **J5** ⟳ | Automatic prep/rest transitions | D E R | With no taps: PREP 5 s → WORK; after submitting a set, REST counts down and WORK of the next set starts at the deadline; block rest → next block automatically; no «Готов»/«Пропустить отдых» primary button; background 60 s across a rest end → on return the next set is already WORK and the countdown matches the server deadline ±1 s; pause survives reload; audio hook list contains `warn_10s`, `count_3/2/1`, `rest_end` at the right offsets and none retroactively |
| **J6** | Custom workout → weekly volume → plan → live → Journal | S W E | User builds a workout, creates a custom plan W1=2, W2=2, W3=0, W4=2; plan shows 2, 2, 0, 2 occurrences (W3 explicitly empty); starting one credits that occurrence («1 из 2»); Journal entry titled with the workout name, editable |
| **J7** | Direct workout does not credit the plan | S W E | Workout Detail «Начать» on a workout that is also planned this week → completed session, plan still «0 из N»; cloning a planned session does not change «N из M» |
| **J8** | Post-factum existing workout keeps identity and is editable | S W E | «Тренировку из моих» for workout X → Journal title = X (not «Тренировка»); «Изменить»/«Повторить»/«Открыть тренировку» available; edit a value → saved; X's workout history and the exercise's analytics panel include the session |
| **J9** | External activity | S W E | «Другую активность» run 45 min → Journal card «Бег · 45 мин»; Analytics total +1, minutes +45, category «Другая активность»; no exercise panel changes; editable duration/type; no plan credit |
| **J10** ⟳ | Edit session → Journal + Analytics converge | S W E | Edit date of a live session to the previous week and a set value: Journal moves the card to that day, duration unchanged, Analytics weekly series moves the workout and its minutes to that week, exercise history shows the new value; totals unchanged |
| **J11** | min_rest_days prevents invalid main placement/start | D S W E | With last main on Mon and `min_days_between_starts` = OD-2 value: plan shows the next main occurrence «доступно с <date>»; server rejects start before it with `too_early{available_from}` on v2 live, legacy API and bot; week capacity shows «не успеть на этой неделе» for infeasible occurrences (example in PROGRAM_PLAN §4 K2); post-factum log of an earlier date allowed and flagged |
| **J12** | Future-week visibility/startability | S W E | Weeks +1…+4 visible; a future-week course occurrence starts (no 422) when spacing/access allow; completing it credits that future occurrence; current week unchanged |

Cross-cutting assertions in every E journey: no raw slug or id in visible text; no «0.5»
workout; no «0:00»/«0 повт.» fake targets; names identical across Detail, Plan, Live, Summary,
Journal (WORKOUT §7).
