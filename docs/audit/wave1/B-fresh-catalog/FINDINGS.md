# FINDINGS — B-fresh-catalog (fresh user, install = migrations + catalogue scripts)

Repro prefix (all findings): S0 = new tg id signed with `BOT_TOKEN=audit-token`, UI onboarding done (baseline 8 → questionnaire), nothing else. Server :8092, DB `pullup_audit_d`. Artifacts under `artifacts/`; per-session event logs `artifacts/<name>.log`. DIAG lines were read only after the failure was observed.

Headline: with the catalogue present, the release-gate path (Home → Подтягивания → «Добавить в план» → Планы → Начать → Live → Завершить → Журнал → Аналитика) WORKS end to end for a new user, including reload and a new browser context. The owner's symptoms are reproduced by F-01 (silent loss of the first add-to-plan), F-08 (plan weeks ≥2 empty), F-07/F-11 (empty/thin custom-workout paths) and, on an install without the catalogue, by the absence of any program/exercise (B-fresh-clean's scope).

---
## F-B-fresh-catalog-01 — first "Добавить в план" for a user with no plan is saved but invisible (P1, frontend state defect + API)
- Journey/step: J2 (workout) and search→exercise (J4), first plan action of a user who has never added a program.
- Expected: item appears in current week (Ср / Свободный пул) after «Добавить» and after reload.
- Actual: sheet closes, Планы shows «Текущая неделя · 0 из 0» / «На эту неделю пока ничего не запланировано.»; same after reload. The POST returned 200, no error shown. Adding the same workout a second time (plan now exists) works and shows «СРЕДА / Моя тренировка спины / 0/1 / Начать». The first (orphan) item can never be seen or removed from the UI.
- Repro: S0 → «Создать тренировку» «Моя тренировка спины» → add exercise → detail → «Добавить в план» → Ср → «Добавить» → Планы. Also: Home search «Планка» → «Добавить в план» → Пн → «Добавить» (user 7200003).
- Evidence: `artifacts/j2-01-after-add.png`, `j2-02-plans.png`, `search-01-after-add.png`, `search-02-plans.png`, `j2.log`; API `GET /api/v2/plan` returned `plan_items:[{id:3,…,"day_of_week":2,"plan_week_id":null,"program_inclusion_id":null}]` with `plan_weeks:[{id:2,…}]`; DB `plan_items` row 3 has `plan_week_id NULL`.
- DIAG: `AddToPlanScreen.tsx:56-66` — `fetchPlan` returns null when the user has no plan, so `planWeekId` = null is sent (`:96`); `app/web/routes_v2.py:1024-1039` accepts `plan_week_id=None`, lazily creates the plan + week 1 and stores the item without a week; `DashboardScreen.tsx:741,973` render only `item.plan_week_id === week.id`. Spec: `journeys.spec.ts` "J2b" (fails by design).
- Severity P1 (user action silently lost; matches owner's "plan with zero workouts"). Layer: frontend state defect / API backend defect.

## F-B-fresh-catalog-02 — strength block promised 4 sets, Live gives 1 (P2, legacy/v2 convergence defect)
- Journey/step: J1, Планы → Начать → pre-session → Live.
- Expected: pre-session «ЦЕЛЬ 2: 3 ПОВТОРЕНИЙ / 4 рабочих подхода · собственный вес» and Program Detail «Блок Б … (старт: 3 повт. × 4 подх.)» ⇒ 4 sets.
- Actual: Live shows «1 / 1 … Подход 1/1 · Цель: 3 повт.»; after one set «ГОТОВО Все подходы плана выполнены». Summary «— 1/1 , выполнено». Session 1 total «4 Подходов» (3+1).
- Evidence: `j1-01-after-start.png`, `j1-01-stuck8.png`, `j1-01-summary.png`; DB `set_targets` for block 2 = 1 row.
- DIAG: `app/services/live_session.py:434-446` deliberately uses `role_state.get("work_sets", 1)`; block_b has no `work_sets` in `program_inclusion.py:66-95` progression_state (STRENGTH_BLOCK.work_sets=4 in `app/domain/constants.py:91` unused here). Comment calls it an intentional simplification, contradicting the UI copy.
- Severity P2. Layer: legacy/v2 convergence defect (UI copy vs execution).

## F-B-fresh-catalog-03 — catalogue contains exactly one program (P2, missing system content)
- J1 "try every program": table below. Only «Подтягивания» exists after `seed_catalog`.
  | Program | #PlanItems visible this week (week 1, after add) |
  |---|---|
  | Подтягивания (id 1) | 1 row «Подтягивания 0/3» in Свободный пул (DB has 2 plan_items: block A ×3, block B ×3; UI merges into one session row). «На этой неделе: 0 из 3». Week 2, 3 …: 0 rows (F-08) |
- Evidence: `j1-01-plans-after-add.png`, Home `onb-02-reload.png`. Layer: missing system content. Severity P2 (catalogue is thin; also no «Начни с подтягиваний» content, F-13).

## F-B-fresh-catalog-04 — session summary shows blank exercise names and unlabeled "Новая цель" (P2, frontend/API)
- J1 step: summary after finishing the program session.
- Expected: block titles («Подтягивания — объём»/«— сила») and labelled targets.
- Actual: «— 3/3 , выполнено» and «— 1/1 , выполнено» (name empty before the dash); «Новая цель 10 → 10 / 3 → 3» with no block labels. For the custom workout the name is present («Австралийские подтягивания — 3/3 , выполнено»).
- Evidence: `j1-01-summary.png`. DIAG not pursued beyond observation (names of internal block exercises are probably filtered). Severity P2; layer frontend state defect / API.

## F-B-fresh-catalog-05 — raw internal slugs shown to users (P3, UX)
- Verbatim: Home category title «pull_ups»; Program Detail eyebrow «PULL_UPS»; search filter chip «pull_ups», exercise subtitles «pull_ups»; Аналитика «По типам: pull_ups / user / …», Сводка rows «pull_ups, block_a, block_b, user» (including «Итого 1 1» with 0.5 fractions).
- Evidence: `onb-02-reload.png`, `j1-02-program-detail.png`, `j1-02-analytics.png`, `j2-03-analytics.png`, `empty-05-E-search.png`. Layer: UX / missing localisation of category labels. P3.

## F-B-fresh-catalog-06 — journal/analytics naming and minutes for non-workout sessions (P3)
- Plank run from plan row: Журнал title «Тренировка» (not «Планка»); Аналитика minutes 1 for a 0:40 set; custom workout minutes 0 («user 1 0»). Evidence: J4 log line 06:14:44, `j2-03-analytics.png`. Layer: API/frontend mapping. P3.

## F-B-fresh-catalog-07 — empty workout: «Начать» disabled with no reason; «Добавить в план» enabled then rejected (P3, UX)
- Detail of «Пустая»: «Пока без упражнений … Начать» (button disabled, no hint). «Изменить» is the way forward (works). «Добавить в план» → Свободный пул → «Добавить» → red text «Не удалось добавить: У выбранной тренировки нет упражнений» (HTTP 422). Not a dead end, but the guard shows only after submit.
- Evidence: `j3-01-empty-detail.png`, `j3-01-empty-in-plan.png`. P3.

## F-B-fresh-catalog-08 — program plan has nothing for weeks ≥2; "next week" silently creates empty weeks (P2, plan-generation defect)
- Journey/step: J4. After adding «Подтягивания», week 1 has the pool row; tapping › creates «Неделя 2 · 12 окт – 18 окт» → «0 из 0 / На эту неделю пока ничего не запланировано.» Copy week 1→2 for a program-only week returns «Скопировано: 0, пропущено дублей: 0» (confirm text only mentions «своих тренировок и упражнений»). Tapping › again creates weeks 3 and 4 (`POST /api/v2/plan/weeks` 200 each, week persists after reload).
- Offered: only «+ Добавить упражнение». Program rows are never generated for later weeks (and the program row «Подтягивания, без дня» has no actions menu, no day/move).
- Evidence: `j4-01-next-week.png`, `j4-01-after-confirm-copy.png`, `j4-01-week3.png`, `j4.log`. DIAG: not pursued beyond note in `scripts/backfill_multi_program.py` docstring («недельная матрица … НЕ заводится»). Severity P2 (by-design for a non-weekly program but UI says «Курс в плане» with 0 workouts). Layer: plan-generation defect / UX.

## F-B-fresh-catalog-09 — unbounded week creation by browsing (P3, UX/API)
- Subsumed in F-08: each › on the last week POSTs a new PlanWeek. P3.

## F-B-fresh-catalog-10 — `scripts/seed_exercise_library.py` cannot run as documented (P2, seed/ops)
- Command from the script's docstring: `python scripts/seed_exercise_library.py` → `sqlalchemy.exc.NoReferencedTableError: Foreign key associated with column 'exercises.owner_user_id' could not find table 'users'`. Works only if `app.db.models` is imported first (my wrapper `scripts/audit/b_fresh_catalog_seed_library.py`).
- Evidence: `artifacts/seed_exercise_library_standalone_error.txt`. Layer: seed/test illusion (tests import all models; operator run does not). P2.

## F-B-fresh-catalog-11 — exercise library is two exercises + internal "Факультатив" items; no pull-up exercise (P2, missing system content)
- Picker/search for a fresh user lists «Факультатив — подтягивания на максимум / W / 3 минуты подтягиваний / на объём», «Планка», «Отжимания»; search «подтягивания» returns only the «Факультатив …» rows; «Подтягивания — объём/сила» are hidden. Create-own path works (PASS): «Создать своё: «Австралийские подтягивания»» → protocol sheet → added, persisted after reload (also appears as a normal library row afterwards).
- Evidence: `j2-01-picker.png`, `j2-01-search-aus.png`, J2 log 06:07:23. Layer: missing system content. P2 (a custom pull-up workout starts from nothing useful).

## F-B-fresh-catalog-12 — completion semantics (P3, valid domain difference?)
- Plank run with 1 of 3 sets, summary «Планка — 1/3 , не выполнено», still counted «1/1» in Планы / «Ещё раз». Re-adding a removed program resets the week counter to «0 из 3» although the earlier session remains in Журнал. P3.

## F-B-fresh-catalog-13 — published collection with 0 items; nothing on Home (P3, missing system content)
- `collections`: «Начни с подтягиваний» (is_published=true, 0 `collection_items`; created by migrations) — Home has no collections row. Evidence: `onb-02-reload.png`, PROFILES.md. P3.

## F-B-fresh-catalog-14 — onboarding baseline does not personalise the starting target (P2, UNKNOWN layer; may be a valid domain choice)
- Baseline entered 8 reps. Program Detail «старт: 10 повт. × 3 подх.», Live «Цель: 10 повт.» ×3 (user logged 8, 8, 7). Summary «Новая цель 10 → 10». A new user whose max is 8 is asked for 3×10 first. Evidence: `j1-02-program-detail.png`, `j1-01-live-1.png`. DIAG: `program_inclusion.py:66-70` uses `base_target`/`initial_target_*` from request; the UI sends none. P2 question for product.

## Non-findings / harness notes
- J8: reload mid-Live restores phase+timer (PASS); offline submit shows «Нет сети — подходы сохраняются локально и уйдут батчем при подключении.», after reconnect `phase/next` + `sets:batch` 200 and the set is in `set_logs` (PASS); double-tap «Сохранить и завершить» → exactly one `/complete` (PASS). Browser back / Telegram BackButton during Live UNTESTED (`goBack` leaves the SPA; the app has no browser history, uses Telegram BackButton).
- Program Detail hides the bottom tab bar; after «В плане» the only exit is the Telegram BackButton / reload (`‹` icon button has no accessible name). Platform/UX note, not scored.
- Dark theme: not valid (see EMPTY_STATES.md).
- No 5xx in `/tmp/audit-B-fresh-catalog-uvicorn.log`; the only console error was the expected 422 in F-07.
