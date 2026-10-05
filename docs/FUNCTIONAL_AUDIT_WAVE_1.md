# Functional Differential Audit: Wave 1 (Judge report)

Umbrella: bimoool/pullup-trainer-bot#295. Baseline `develop/current` = `523a930` (branch `claude/wonderful-tesla-2dph8h`, audit-only commits on top).
Inputs: `docs/audit/wave1/HARNESS.md`, `A-reference/`, `B-fresh-clean/`, `B-fresh-catalog/`, `C-existing/`. Companion deliverables:
`docs/FUNCTIONAL_REACHABILITY.md`, `docs/SYSTEM_CONTENT_CONTRACT.md`, `docs/audit/wave1/ISSUE_DRAFTS.md`.
Every finding is **LOCAL only**. Nothing could be staging-confirmed in this wave.

---

## 0. §24 checkpoint

| Question | Answer |
|---|---|
| Fresh user can complete a first workout? | **Clean install (migrations only): NO on the product's primary path** (course → plan → Начать is impossible, FD-01). It is technically YES only through the custom path (Главная → «Своя программа» → type an exercise name → «Создать своё» → Начать), and that path needs a hidden affordance (FD-04). **Catalogue install (migrations + scripts): YES**, end to end incl. reload and a new context (B-fresh-catalog J1 PASS). |
| Existing user can complete a workout? | **YES**: all 10 backfilled profiles started and completed from Планы (C J1/J6/J7/J8). Expired users can too, which is itself a defect (FD-05). Too-early users hit a text dead end (FD-18). |
| PROGRAM | **FAIL** (clean: FD-01 P0; catalogue: week 1 PASS, then FD-08/FD-09 P2) |
| CUSTOM | **FAIL** (FD-02 P1 at the plan step; FD-04 P1 first-exercise discoverability on an empty library) |
| FREE (no plan) | **PASS** (custom workout → Начать → Live → Журнал → Аналитика, both B installs) |
| PLAN | **FAIL** (FD-02 P1 orphaned first add; FD-03 P1 empty-state loop on clean; FD-08 P2 empty future course weeks) |
| LIVE | **PASS** (reload/reopen, offline queue, double-tap finish; P2: FD-09 block Б 1 set, FD-10 target mismatch; Telegram BackButton UNTESTED) |
| JOURNAL | **PASS** with P2 defects (FD-12, FD-14, FD-15, FD-16) |
| ANALYTICS | **PASS** for native sessions; P2 FD-13 (legacy delete/edit not reflected) |
| SUBSCRIPTION | **FAIL** (FD-05 P1 course start not gated; FD-11 P2 stale status, no pay action). Admin grant via bot PASS. |
| PERSISTENCE | **PASS** (reload / new context / offline / reopen), except the invisible orphan row of FD-02 (counted under PLAN) and the history title loss of FD-12 |
| Severity counts (final, deduplicated) | **P0: 1 · P1: 4 · P2: 13 · P3: 8** (26 defects from 47 explorer findings; 2 harness non-defects) |

**TOP 10 BLOCKERS** (dependency-aware): 1 FD-01 empty catalogue on clean install · 2 FD-02 first add-to-plan orphaned ·
3 FD-03 Планы↔Главная CTA loop · 4 FD-04 custom workout has no discoverable first exercise · 5 FD-05 expired users not gated on
the v2 course path · 6 FD-06 catalogue scripts not in deploy, one crashes · 7 FD-07 catalogue (even with scripts) has no
pull-up library exercise and leaks internal exercises · 8 FD-08 future course weeks look empty · 9 FD-09 strength block 1 set
instead of 4 · 10 FD-18 «Начать» on a too-early day dead-ends without a date.

**WHY THE OLD SUITE MISSED THEM** (details in §9):
- All e2e scenarios share one CI database. The first seed (`first_workout`, `scripts/e2e_seed_all.sh:11`) creates a global program
  («Первая тренировка», `scripts/e2e_seed.py:163-195`), so the catalogue was never empty.
- 15 of 41 scenarios inject system content (6 call `seed_exercise_library`, 13 create `Program` rows), and 20 of 41 pre-create
  TrainingPlan / PlanWeek / PlanItem.
- Two seed docstrings state the false premise «каталог программ … приходит из миграций» (`e2e_seed.py:1462-1463`, `:1240`).
- The golden journey pre-creates the plan and the current week (`e2e_seed.py:1332-1340`), which bypasses FD-02. A backend test asserts the
  FD-02 behaviour as "old behaviour" (`tests/test_web/test_v2_plan_items_with_week.py:131-147`).
- The full-sweep "no dead ends" check for E1 only asserts that a button exists (`full-sweep.spec.ts:519-526`).
- No e2e seed creates an expired user. The only `no_access` tests cover legacy endpoints that the v2 start path does not use.
- `seed_exercise_library` is tested by importing the function after `app.db.models` (`tests/test_web/test_v2_exercises.py:24,27`), so
  the operator crash is masked.

---


**Filed issues (P0/P1):** FD-01 → #296 · FD-02 → #297 · FD-03 → #298 · FD-04 → #299 · FD-05 → #300 (sub-issues of umbrella #295). P2/P3 stay in the backlog in `docs/audit/wave1/ISSUE_DRAFTS.md`.

## 1. Environment and limitations

| Item | Value |
|---|---|
| Code | `523a930` and audit-only commits; product code was not modified |
| Installs | **clean** `pullup_audit_b` (`alembic upgrade head` to `9e3f1a4b6c80`: programs 0, exercises 0, complexes 0, assessment_protocols 3, collections 1 with 0 items). **catalogue** `pullup_audit_d` = clean + `scripts/backfill_multi_program.py` (non-dry) + `scripts/seed_exercise_library.py` (crashed standalone; run through the audit wrapper `scripts/audit/b_fresh_catalog_seed_library.py`). `seed_collections.py` was **not run** by anyone. **existing** `pullup_audit_c` = legacy bot users created through bot-era services, the real backfill, and the library seed |
| Client | Playwright Chromium 1194 (renamed binary; harness note B-clean F-14), viewport 390×844, iPhone UA, light theme. `window.Telegram.WebApp` mocked with HMAC-signed initData (`BOT_TOKEN=audit-token`) |
| Reference | **No Crimpd lab** (`~/android-ref-lab` absent). All reference facts are secondhand from repo docs (`A-reference/GOLDEN_TRACES.md`): OBSERVED (secondhand) / INFERRED / UNKNOWN. Empty-state texts of Crimpd are UNKNOWN (8 of 12 rows) |
| Staging/prod | **Unreachable** (forced-command SSH). Nothing is STAGING CONFIRMED. Read-only SQL for the owner: `docs/SYSTEM_CONTENT_CONTRACT.md` §4 |
| Not covered | real iPhone WebView (safe area, keyboard, native BackButton, `window.confirm`), Telegram BackButton during Live, valid dark-theme empty states on the catalogue install (B-catalog mock lacked themeParams), payment flows (Robokassa/Stars), the legacy BackdateForm/WorkoutScreen paths, protocols other than reps/time |
| Correction to the Director brief | `Dockerfile:11` **does** `COPY scripts ./scripts` (since `1685a76`, 2026-09-19) for the `app` (bot) image. `Dockerfile.web` does not. CLAUDE.md and `.claude/skills/deploy-and-verify/SKILL.md:43-48` («scripts/ в образ не попадает») are stale; `.claude/skills/migrations-safe/SKILL.md` («scripts/ копируется в образ») is correct. The conclusion stands: **`deploy/deploy-run.sh:32-38` runs no catalogue script**, so content still reaches an environment only by a manual operator step (folded into FD-06) |

## 2. State profiles (merged)

| Profile | Install | tg ids | How created | AUTH NECESSITY | DOMAIN NECESSITY | SYSTEM CONTENT | TEST CONVENIENCE / INJECTION |
|---|---|---|---|---|---|---|---|
| audit_fresh_active | clean | 7100001/11/14 | UI onboarding only | users row via `/api/hello` | baseline 8, questionnaire, trial 14 d, 50 coins, «Первый замер» (server side effects) | 3 protocols + 1 empty collection (migrations) | none |
| audit_empty_library | clean | 7100012/16/17/72 | UI onboarding only | same | same | same | none |
| audit_fresh_expired | clean | 7100015 (7100003 exploration) | UI onboarding, then injection | same | same | same | **INJECTION** `UPDATE users SET subscription_expires_at = now() - interval '1 day' WHERE telegram_id = 7100015;` |
| audit_fresh_active (catalogue) | catalogue | 7200001–04, 7200011–14 | UI onboarding only | same | baseline 8, questionnaire, trial | Program «Подтягивания» (2 ProgramItems), 6 internal exercises, Планка, Отжимания, 3 protocols, empty collection | none (seed-script wrapper = environment setup) |
| audit_existing_active | existing | 7300001 | bot services: onboarding, band 15 kg, 6 legacy workouts, then the real backfill | users | legacy workouts/blocks, Stars subscription | backfill catalogue + library | back-dated `now`/`performed_at` (service API) |
| audit_legacy_existing | existing | 7300002 | as above + 1 legacy elective; never opened the Mini App | | trial (ends 2026-10-07) | | same |
| audit_returning_week_transition | existing | 7300003 | backfill with `now=-10 d` | | active | | **INJECTION** `scripts/audit/c_inject_week_transition.sql` (deletes the current-week PlanWeek/PlanItems) |
| audit_trial / _rested | existing | 7300004 / 7300007 | 2 workouts (1 d / 4 d ago) | | trial | | back-dated history |
| audit_active_paid | existing | 7300005 | 5 workouts | | Stars active | | |
| audit_expired / _b | existing | 7300006 / 7300008 | trial ended 26 / ~31 days ago, cache still `trial` | | expired by date | | back-dated |
| audit_persist / audit_interrupt | existing | 7300009 / 7300010 | 3 workouts | | active | | |
| admin actor | — | 7300099 | `settings.admin_ids` patched in `scripts/audit/c_admin_grant.py` only | | | | real bot handler via `Dispatcher.feed_update` (not an injection) |

Fresh-user journeys used **no TEST CONVENIENCE**. The only injections (expiry, week transition) are labelled, and the PASS verdicts do not rely on them.

---

## 3. Journey results (J1–J8)

Verdict legend: PASS = visible, survives reload, and enables the next action. Severity is the final FD severity. Reference
column: OBS / INF / UNK = evidence tag from `GOLDEN_TRACES.md`.

### J1: Zero to first workout through a program/plan

REFERENCE TRACE (R-J1): Home catalogue-first (OBS) → discover via category / search / Skill Templates (OBS) → template or workout
detail (OBS) → add to plan through a 2-step sheet (OBS) → plan In Progress (INF) → week view with "0/1" counters (OBS) → start
(INF via Workout Detail) → player → review sheet → Logbook (INF) → Analytics recompute (OBS).
OUR TRACE (catalogue): Home «Подтягивания» card → Program Detail «Добавить в план» → «В плане» → Планы «СВОБОДНЫЙ ПУЛ | Подтягивания 0/3 | Начать» → pre-screen → Live → summary → Журнал «По плану» → Аналитика. OUR TRACE (clean): stops at Home «Каталог курсов появится здесь позже.»

| Step | Reference | Ours: clean | Ours: catalogue | Ours: existing | Result | Sev |
|---|---|---|---|---|---|---|
| Onboarding | UNK | UI onboarding works, resumes after reload | same | not re-asked | PASS (domain difference: baseline + questionnaire + trial is our onboarding) | — |
| Home shows ≥1 program | OBS (category rows) | «Каталог курсов появится здесь позже.» | «Подтягивания» (header shows raw «pull_ups») | «Подтягивания · В плане» | clean **FAIL FD-01**; catalogue PASS (FD-19 slug) | P0 / P3 |
| Планы empty CTA | UNK (INF templates / blank plan) | «Выбрать курс на Главной» → Home (empty) → «Откройте план дня» → Планы: loop | resolves to the card | n/a | clean **FAIL FD-03** | P1 |
| Program Detail → add | OBS (2-step sheet) | BLOCKED BY FD-01 | «Добавить в план» → «В плане», persists after reload | already in plan | PASS (domain difference: one plan per user, no new/existing step, PROJECT_SPEC) | — |
| Current week has an actionable row | INF | BLOCKED | «Текущая неделя · 0 из 3 | СВОБОДНЫЙ ПУЛ | Подтягивания 0/3 | Начать» | same; returning user: week auto-created | PASS | — |
| Pre-screen == Live plan | n/a | BLOCKED | pre «ЦЕЛЬ 2: 3 ПОВТОРЕНИЙ / 4 рабочих подхода», Live block Б «1 / 1» | same «— 0/1»; gap users pre 9 vs Live 11 | **FAIL FD-09**, **FD-10** | P2 |
| Start from baseline | UNK | — | baseline 8 → «старт: 10 повт. × 3 подх.» | baseline-based (backfill) | **FD-17** (product question) | P2 |
| Live → finish → summary | OBS | BLOCKED | completes; summary «— 3/3 , выполнено» with blank names | «— 2/4 , не выполнено … Не выполнено — осталось в плане.» | PASS (FD-16 names) | P2 |
| Журнал + Аналитика + new context | INF / OBS | BLOCKED | «По плану | Подтягивания | … Повторы 26»; Аналитика 1 | PASS for all 3 profiles | PASS | — |

Verdict: **clean FAIL (BLOCKED BY FD-01) · catalogue PASS · existing PASS**.

### J2: Custom workout from nothing → exercise → save → start → add to plan → start from plan

REFERENCE TRACE (R-J2): Create Custom Workouts (6-step wizard, OBS) → add exercise: search + list, no-match row "Create Exercise: <query>" (OBS) → protocol stepper (OBS) → save → My Workouts (OBS) → Start (OBS) → Add to Plan 2-step sheet (OBS) → start from plan (INF).
OUR TRACE: «Своя программа» / «Создать тренировку» → name → editor «Пока пусто…» → «+ Добавить упражнение» → picker → type → «Создать своё: «X»» → protocol sheet → «Добавить» → «Сохранить» → detail → Начать / «Добавить в план» → day → «Добавить».

| Step | Reference | Clean | Catalogue | Result | Sev |
|---|---|---|---|---|---|
| Entry point | OBS banner/"+" | «Своя программа», «Создать тренировку» | same | PASS (domain difference: name-first form, not a 6-step wizard; documented in UXA:37) | — |
| Picker on an empty or thin library | UNK size; OBS search + "Create Exercise" | «Ничего не найдено» + hint «Нет нужного? Введите название, и появится «Создать своё».»; no visible CTA until typing | list = 4 «Факультатив — …» + Планка + Отжимания; «подтягивания» finds only Факультатив | **FAIL FD-04** (clean), **FD-07** (catalogue) | P1 / P2 |
| No-match → create own | OBS "Create Exercise: Xxx" | «Создать своё: «Подтягивания»» → protocol sheet | «Создать своё: «Австралийские подтягивания»» | PASS (matches reference). Note FD-23: the exercise persists before confirmation | P3 |
| Protocol → save → reload | OBS | «3 × 10 повторений · отдых 1:00», persists | «3 × 8», persists | PASS (domain difference: 4 protocol types, UXA:37) | — |
| Start directly → Live → finish | OBS | PASS (reload mid-rest restores timer) | PASS | PASS | — |
| **First «Добавить в план» (user has no plan)** | OBS 2-step sheet | sheet closes; Планы «Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано.» (also after reload) | identical | **FAIL FD-02** | P1 |
| Second add (plan exists) | — | «ЧЕТВЕРГ | Мои подтягивания | 0/1 | Начать» | «СРЕДА | Моя тренировка спины | 0/1» | PASS (hides FD-02 on retry) | — |
| Start from plan → finish | INF | summary + «Прогрессия не пересчитана — нет активного курса…» | same | PASS (FD-20 jargon P3; FD-21 «1/1 · Ещё раз» after 2 of 3 sets) | P3 |
| Remove plan row → Журнал | UNK (INF history survives) | «По плану | Мои подтягивания» becomes «По плану | Тренировка» | Планка becomes «Тренировка» | **FAIL FD-12** | P2 |

Verdict: **FAIL on both installs** (FD-02; clean also FD-04).

### J3: Free workout without a plan

REFERENCE (R-J3): Workout Detail → Start; no plan prerequisite (OBS); Logbook (INF). OURS: custom workout detail → «Начать» → «ГОТОВЫ К СТАРТУ» → Live → summary → Журнал «Свободная» → Аналитика.

| Step | Reference | Clean | Catalogue | Result | Sev |
|---|---|---|---|---|---|
| Reachable workout | OBS catalogue or My Workouts | only a user-built workout (no system workouts) | same (0 complexes) | PASS; system workouts absent = FD-07 / owner decision D2 | P2 |
| Start → Live → finish → Журнал «Свободная» → Аналитика | OBS / INF | PASS (Аналитика «user 1 · 100%») | PASS | PASS (FD-19 raw «user», minutes 0) | P3 |
| Zero-exercise workout | UNK | «Начать» disabled, no reason; «Записать» → «Введи хотя бы один подход» | same; «Добавить в план» → «Не удалось добавить: У выбранной тренировки нет упражнений» | FD-04 | P1 |

Verdict: **PASS** (clean and catalogue). Existing profiles: not run as a separate journey.

### J4: Plan lifecycle

REFERENCE (R-J4): tabs In Progress / Upcoming / Completed (OBS); week stepper (OBS); "0/1" counters (OBS); move day (OBS); "Clone plan" label only (copy-week NOT observed); empty week and new week UNK.

| Step | Reference | Clean | Catalogue | Existing | Result | Sev |
|---|---|---|---|---|---|---|
| E1 empty → CTA | UNK | loop (FD-03) | resolves | — | clean FAIL | P1 |
| First manual add | — | orphaned (FD-02) | orphaned (FD-02) | — | FAIL | P1 |
| Move day / free pool / other week + reload | OBS move | PASS | PASS (also to week 2) | — | PASS | — |
| Copy week | not in reference (domain extension) | «Скопировано: 1, пропущено дублей: 0» | course-only week: «Скопировано: 0, пропущено дублей: 0» | — | PASS manual; course rows not copied **by spec** (PROJECT_SPEC.md:684-685) → FD-08 UX | P2 |
| Future week of a course | UNK (E10/E11) | n/a | «Неделя 2 · 0 из 0 | На эту неделю пока ничего не запланировано.» | — | **FD-08** (spec'd: PROJECT_SPEC.md:677-680; `app/services/plan_week.py:121-142`), unexplained in UI | P2 |
| › past the last week | UNK | creates week 3 silently | creates weeks 3, 4 | — | FD-08 (P3 part) | P3 |
| Week rollover for a returning user | INF | — | — | «Неделя 1 · 5 окт – 11 окт», «0 из 3», startable | PASS (upstream S0 injected) | — |
| Remove course («История сохранится») → Завершённые → re-add | UNK (R6) | BLOCKED BY FD-01 | PASS; re-add resets «0 из 3» (FD-21) | — | PASS | P3 |
| Remove manual row | UNK | PASS, but Журнал title lost (FD-12) | same | — | FAIL FD-12 | P2 |

Verdict: **clean FAIL · catalogue FAIL (FD-02) · existing PASS** (week transition).

### J5: Journal lifecycle (existing users; C)

REFERENCE (R-J5): Logbook cards → detail sheet with View/Edit/Clone/Delete (OBS); Edit/Clone forms UNK; delete with confirmation (OBS); Analytics recompute on add/delete (OBS secondhand A8).

| Step | Reference | Ours (audit_existing_active / audit_legacy_existing) | Result | Sev |
|---|---|---|---|---|
| Open a native plan session | OBS sheet with 4 actions | sheet «Открыть / Отмена»; detail read-only, both blocks titled «Упражнение» | **FAIL FD-14**, FD-16 | P2 |
| Backdate an activity + reload + Аналитика +1 | OBS | «Плавание 0:40», 7 → 8 | PASS | — |
| Edit activity | OBS (form UNK) | rating/comment persist; duration/type not editable | PASS (FD-24) | P3 |
| Clone activity | OBS (form UNK) | «Записана задним числом | Тренировка | Подходы — | Повторы —»; «Без категории» in Аналитика | **FAIL FD-15** | P2 |
| Delete activity + reload + Аналитика −1 | OBS | 9 → 8 | PASS | — |
| Legacy edit + reload | — | «Объём (резина): 9, 10, 10» persists | PASS | — |
| Legacy delete → Аналитика | OBS recompute | Журнал entry gone; «Тренировок за 30 дней» 5 → 5 | **FAIL FD-13** | P2 |
| Backfilled elective card | — | «Подходы 1 | Повторы 36» for a 4-set ladder | FD-26 | P3 |

B profiles: Журнал PASS for created sessions; FD-12 title loss (both installs).

### J6: Subscription states

Rule (governs FD-05): `docs/plan-and-specs.md` §14 (lines 337-341), «Дефолт [подтвердить]», in force until the owner decides
(§16 line 364: «иначе агент работает по дефолту»):
- free forever: замер, тесты, **свободные тренировки** и внесение задним числом, история, аналитика;
- trial 14 days: full access;
- subscription: active courses in the plan, plan editor, catalogue. **«Без подписки после триала: курсы в плане ставятся на паузу
  (не удаляются), кнопка «Начать» → экран подписки; данные не теряются.»**
- also §10.3 line 212: course card for an expired user → «Доступно по подписке» → subscription screen.

`docs/PROJECT_SPEC.md` and `.specify/memory/constitution.md` contain no access rule. `docs/payments.md` covers only the `ADMIN_IDS` bypass
and Robokassa polling. Legacy precedent: `app/web/routes.py:736-737` (`/api/workout/plan` → `no_access`), `:1710-1711` (backdate),
and the bot gate `app/bot/handlers/workout.py:247`. Electives are deliberately not gated (`docs/mini-app.md:768-771`).

REFERENCE: Crimpd+ upsell exists (OBS P1); which actions are gated is UNK.

| Profile | Step | Ours | Result vs rule | Sev |
|---|---|---|---|---|
| audit_trial (1 d rest) | Планы → Начать | «Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл.» → screen with «Перейти в обычную "Тренировку"», no date | valid rule (MIN_REST_DAYS), UX dead end **FD-18** | P2 |
| audit_trial_rested / active_paid | start → complete → Журнал | PASS (pre 11 = Live 11; 8 = 8) | PASS | — |
| audit_expired / _b (C) | Планы | banner «Нет активной подписки. Оформи её в боте, потом возвращайся сюда.»; «Начать» enabled; course session completed and saved | **FAIL FD-05** (violates §14: course «Начать» must lead to the subscription screen) | P1 |
| audit_expired (C) | Профиль | «Подписка : пробный период (осталось 0 дн., до 09.09.2026)» while Планы says no subscription | **FD-11** | P2 |
| audit_fresh_expired (clean) | all tabs; create and start a custom workout | no gating anywhere; «Оплата картой временно недоступна.»; no pay button | custom/free workout: **allowed by §14** (not a defect). Missing pay action and stale label: **FD-11** | P2 |
| expired → admin grant (bot handler) | state kept, banner gone, trains | PASS («Подписка на 30 дней выдана @audit_expired.») | PASS | — |

### J7: Persistence

| Item | Clean | Catalogue | Existing | Result |
|---|---|---|---|---|
| Onboarding resume, workouts, exercises, protocol, plan rows (manual/moved/copied), weeks, course removal | PASS | PASS | — | PASS |
| Finished session in Журнал in a new browser context | PASS | PASS | PASS | PASS |
| Reopen mid-rest (context closed) | — | — | resumes in ОТДЫХ (1:25), but the «Подход 1: 10 повт. · Изменить» chip is gone; the set is kept | PASS (FD-25 P3) |
| First add-to-plan row | invisible forever | invisible forever | — | FAIL FD-02 |

REFERENCE (R-J7/J8): resume after kill / back during a session is UNK. Native background timer INF.

### J8: Live resilience

| Item | Ours (catalogue / existing) | Reference | Result |
|---|---|---|---|
| Reload mid-Live | phase + timer restored («ОТДЫХ 1:28») | UNK | PASS |
| Offline set → reconnect | «Нет сети — подходы сохраняются локально и уйдут батчем при подключении.»; `sets:batch` 200; set_logs correct | UNK | PASS |
| Double-tap «Сохранить и завершить» | one `/complete`, one session | UNK | PASS |
| Browser Back | harness leaves to about:blank; reopening resumes (C) | UNK | PASS (platform difference: the app uses the Telegram BackButton) |
| Telegram BackButton during Live | — | UNK | **UNTESTED** |

---

## 4. Empty-state matrix (merged; canonical numbering from A-reference)

| # | SCREEN | MESSAGE (verbatim) | CTA | CTA resolves? | REFERENCE (A) | OUR RESULT | Defect |
|---|---|---|---|---|---|---|---|
| E1 | Планы → Сейчас, no plan | «Текущий план» / «Курсов в плане нет. Добавьте курс на Главной.» | «Выбрать курс на Главной»; Home banner «Готовы заниматься? / Откройте план дня» → Планы | clean **NO** (loop; Home «Каталог курсов появится здесь позже.»); catalogue YES | UNK (INF Skill Templates / blank plan) | clean FAIL · catalogue PASS | FD-03 (root FD-01) |
| E2 | Планы, plan exists, current week 0 rows | «Текущая неделя · 0 из 0» / «На эту неделю пока ничего не запланировано.» (clean: card above still «Курсов в плане нет…», FD-22) | «+ Добавить упражнение» (sheet with day picker) | partly: works if the library is non-empty; **reached wrongly right after the first add** | UNK | FAIL (as a symptom) | FD-02 |
| E3 | Главная «Мои тренировки» / Планы → Мои тренировки, 0 workouts | «Соберите свою тренировку из упражнений и протоколов.» / «У вас пока нет своих тренировок» | «Создать тренировку» | YES | INF (banner "Create Custom Workouts") | PASS | — |
| E4 | Exercise picker, empty library (clean) / thin library (catalogue) | clean: «Выберите упражнение — на следующем шаге настроите подходы и отдых. Нет нужного? Введите название, и появится «Создать своё».» + «Ничего не найдено»; catalogue: 4 «Факультатив — …» + Планка + Отжимания | «Создать своё: «<текст>» +» only after typing | YES after typing | OBS "Create Exercise: <query>" on no match; size UNK | clean PARTIAL · catalogue PASS (content FD-07) | FD-04, FD-07 |
| E4b | Picker, no match | «Ничего не найдено» | «Создать своё: «zzz» +» → protocol sheet → «Добавить» | YES | OBS (same pattern) | PASS | (FD-23 persists before confirm) |
| E5 | Журнал, 0 sessions | «В этом месяце тренировок нет» | «+ Записать» («Тренировку из моих» / «Другую активность») | YES («Тренировку из моих» with 0 workouts UNTESTED) | UNK | PASS | — |
| E6 | Аналитика, 0 sessions | «0 Тренировок за 30 дней», «За выбранный период нет данных.», «Пока нет завершённых тренировок из «Мои тренировки» — показатели по упражнениям появятся после первой.» | none (CSV «Скачать» still offered) | n/a | UNK | PASS (informational) | — |
| E7 | Тесты / Профиль → ТЕСТЫ, no results | «Ещё не проходили» / «Для графика нужно хотя бы два результата.» / «Запишите результат, чтобы сравнить себя с похожими.»; Профиль: «Тренировок пока не было.», ГТО «Внеси первую тренировку, чтобы узнать свой разряд ГТО.», WSF «Внеси тренировку блока Б на отягощении или собственном весе, чтобы узнать свой разряд WSF.» | «Записать результат» form | YES (form not submitted) | UNK | PASS | — |
| E8 | Главная «Избранное», none | section hidden while empty | — | n/a | UNK | UNTESTED as a message; add path PASS | — |
| E9 | Expired subscription | Профиль → Подписка «Статус | пробный период (осталось 0 дн., до 04.10.2026)», then «истекла»; «Оплата картой временно недоступна.»; Планы (course user) «Нет активной подписки. Оформи её в боте, потом возвращайся сюда.» | none (no pay button; «Открыть текст оферты» only); «Начать» stays enabled | **NO** | INF (Crimpd+ upsell exists, gating UNK) | FAIL | FD-05, FD-11 |
| E10 | Newly created week (›) | «Неделя 3 · 19 окт – 25 окт» «0 из 0» «На эту неделю пока ничего не запланировано.» | «+ Добавить упражнение» | YES for manual plans | UNK ("Schedule" label only) | PASS (manual) / PARTIAL (course plan, FD-08) | FD-08 |
| E11 | Course yields no workouts | clean: BLOCKED BY FD-01; catalogue: week 1 PASS («Подтягивания 0/3»), weeks ≥2 show E10 text | — | n/a | UNK | BLOCKED / PARTIAL | FD-01, FD-08 |
| E12 | Custom workout with zero exercises | editor «Пока пусто. Добавьте первое упражнение и настройте, как его выполнять.»; detail «Пока без упражнений» / «В тренировке пока нет упражнений» / «Вы ещё не выполняли эту тренировку» | editor «+ Добавить упражнение» (YES); detail: «Начать» disabled without reason, «Добавить в план» → «Не удалось добавить: У выбранной тренировки нет упражнений», «Записать» → «Введи хотя бы один подход»; «Изменить» is the way out | editor YES; detail only via «Изменить» | INF ("+ Add Exercise" tail control) | PARTIAL | FD-04 |
| extra | Планы → Завершённые | «Завершённых курсов пока нет. Убранные из плана курсы появятся здесь.» | none | n/a | UNK | PASS | — |
| extra | Search, no results | «Найдено: 0» / «Ничего не найдено» | chips «Сбросить» | n/a | OBS search | PASS | — |
| extra | Home collections | no row although «Начни с подтягиваний» is published (0 items) | — | n/a | OBS curated playlists | hidden (acceptable); content missing FD-07 | FD-07 |

Dark theme: B-clean dark pass valid (readable, no layout break). B-catalog dark pass INVALID (mock without themeParams), so it is UNTESTED there.

---

## 5. Reference comparison: differences and reasons

| Difference | Classification | Reason |
|---|---|---|
| One plan per user; add-to-plan has a day picker, not "new/existing plan" | valid domain difference | PROJECT_SPEC (plan = single TrainingPlan); Crimpd's 2-step sheet is OBS, but a multi-plan model was never adopted |
| Name-first builder with 4 protocol types vs a 6-step wizard with no protocol picker | valid domain difference | UXA:37 documents it |
| Copy week (ours) vs "Clone plan" label (Crimpd) | domain extension | #275 |
| Readiness gate MIN_REST_DAYS («Ещё рано…») | valid domain difference (rest_policy is "только наше", plan-and-specs.md:75) | only its UX dead end is a defect (FD-18) |
| Start from a plan row («Начать» on the row) vs Crimpd row → detail → Start (INF) | reference-only difference | improvement, not a regression |
| Home catalogue-first | matches the reference **only if the catalogue exists** | FD-01 breaks the parity premise |
| Crimpd ships a system exercise library and catalogue workouts (OBS/INF) | **material difference** | FD-01 / FD-07 / owner decision D2 |
| Telegram BackButton vs Android Back | platform difference | untested |

---

## 6. Final defects (FD-NN)

Severity model: P0 = core value impossible or dangerous; P1 = core flow materially broken or needs a hidden or manual workaround;
P2 = works but differs materially; P3 = polish. All defects are **LOCAL only**.

### FD-01 [P0] Clean install has no training catalogue, so the course path is impossible for every fresh user
- REFERENCE BEHAVIOR: Home is catalogue-first: category rows "N Workouts", Skill Templates, exercise library (OBS, R-J1 R2–R4; R-J2 R4).
- OUR BEHAVIOR: after `alembic upgrade head` there are 0 programs, 0 exercises and 0 complexes. Home shows «Каталог курсов появится здесь
  позже.»; `GET /api/v2/programs` → `{"programs":[]}` and `/api/v2/exercises` → `{"exercises":[]}`.
- FIRST DIVERGENCE: J1 step "Home shows ≥1 program card".
- USER IMPACT: the core value (a progressive pull-up course with a plan) cannot start on any environment deployed by
  `deploy/deploy-run.sh` (build → `alembic upgrade head` → up, lines 32-38) unless an operator ran the scripts by hand. This
  causes FD-03 (CTA loop) and FD-04 (empty picker), and it leaves the custom path as the only way to train.
- SEVERITY: **P0**. B-clean suggested P0; I confirm it. "Core value impossible" holds on any such install. It is environment-conditional:
  a catalogue install passes, and staging state is UNKNOWN.
- REPRO from S0: empty DB → `alembic upgrade head` → open the Mini App as a new user → onboarding → Главная.
- EVIDENCE: `docs/audit/wave1/B-fresh-clean/artifacts/J1-home-catalogue.png`, `after-onb.png`, `api-programs.json`, `api-exercises.json`,
  `trace-J1.log`; contrast `B-fresh-catalog/artifacts/onb-02-reload.png`.
- ROOT CAUSE (confirmed): no migration inserts programs or exercises (only `f6a7b8c9d0e1` protocols and `9e3f1a4b6c80` collections, whose
  items are filled only if programs already exist, `:18-23,64-71`). Content exists only in `scripts/backfill_multi_program.py::seed_catalog`
  (`:245-290`, side-effecting backfill) and `scripts/seed_exercise_library.py`. Neither is invoked by deploy. Render: `webapp-frontend/src/HomeScreen.tsx:420-422`.
- LIKELY LAYER: missing system content (and seed/test illusion, see §9).
- SOURCES: F-B-FRESH-CLEAN-01; context F-B-fresh-catalog-03; Director environment facts. **LOCAL only.**

### FD-02 [P1] The first «Добавить в план» from a user without a plan is saved as an orphan (`plan_week_id = NULL`) and never shown
- REFERENCE BEHAVIOR: "Add to Plan" places the workout in the plan (OBS W5/F8). The added row appears in the week (INF).
- OUR BEHAVIOR: the sheet closes with no error; Планы shows «Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано.» before and after
  reload. A second add works and hides the problem. The orphan row cannot be seen or removed.
- FIRST DIVERGENCE: J2 / J4 first plan action (exercise or workout) of a user with no TrainingPlan.
- USER IMPACT: the user's first planning action is silently lost; matches the owner's "adding a plan → zero workouts". The orphan rows
  accumulate in the DB.
- SEVERITY: **P1**. B-clean suggested P0. I downgrade it: retry works, no history is lost and the free start still works. It stays the top P1,
  because on a clean install the custom path is the only path and every new user hits this on the first try.
- REPRO from S0: onboard → Главная → «Создать тренировку» → name → «+ Добавить упражнение» → «Создать своё: «X»» → «Добавить» → «Сохранить» →
  «Добавить в план» → «Ср» → «Добавить» → reload → Планы. The same happens through Home search «Планка» → «Добавить в план» on a catalogue install.
- EVIDENCE: `B-fresh-clean/artifacts/J2-plan-after-add.png`, `J4-plan-exists-week-0.png`, `api-plan-orphan.json`, `trace-J2.log` (06:44:48),
  `trace-J4.log` (06:45:57); `B-fresh-catalog/artifacts/j2-01-after-add.png`, `j2-02-plans.png`, `search-01-after-add.png`, `search-02-plans.png`, `j2.log`.
  Request `POST /api/v2/plan-items {"complex_id":2,"plan_week_id":null,"day_of_week":2,"count_per_week":1}` → 200.
- ROOT CAUSE (confirmed by Judge):
  - `webapp-frontend/src/AddToPlanScreen.tsx:56-66`: `fetchPlan` returns `null` when no plan exists (`apiV2.ts:358-361`), so
    `planWeekId = null`, which is sent at `:96`.
  - `app/web/routes_v2.py:1002` creates the plan (`get_or_create_for_user`). The week check runs only `if body.plan_week_id is not None` (`:1025`),
    so the item is stored with `plan_week_id=body.plan_week_id` = NULL (`:1036-1040`).
  - `app/services/plan_week.py:88-94` attaches unweeked rows **only for program inclusions** (`list_unweeked_plan_items(program_inclusion_id=…)`),
    so manual NULL rows are never attached.
  - `webapp-frontend/src/DashboardScreen.tsx:973` renders rows only where `item.plan_week_id === week.id`.
  - A test codifies the defect: `tests/test_web/test_v2_plan_items_with_week.py:131-147` («plan_week_id не передан → старое поведение сохраняется», asserts `plan_week_id is None`).
- LIKELY LAYER: API/backend defect + frontend state defect.
- SOURCES: F-B-FRESH-CLEAN-03, F-B-fresh-catalog-01 (same defect). **LOCAL only.**

### FD-03 [P1] Empty Планы CTA «Выбрать курс на Главной» and Home «Откройте план дня» form a closed loop when the catalogue is empty
- REFERENCE BEHAVIOR: "no dead ends" principle (SKL rule 4). Crimpd's E1 is UNK (INF: templates and blank plan).
- OUR BEHAVIOR: Планы «Курсов в плане нет. Добавьте курс на Главной.» → «Выбрать курс на Главной» → Главная «Каталог курсов появится здесь позже.» →
  «Откройте план дня» → Планы. Three taps, no state change, and no offer of «Создать тренировку» from Планы.
- FIRST DIVERGENCE: J1 / J4 E1.
- USER IMPACT: the owner's "sometimes no plan" with no way forward; a new user on a clean install is told to choose a course that does not exist.
- SEVERITY: **P1** (dead-end empty state). B-clean suggested P0. I downgrade it: it is a consequence of FD-01, and Home still shows «Своя программа» / «Создать тренировку».
  It drops to P2 once FD-01 ships, but it is still needed for catalogue fetch errors and for users who want only custom training.
- REPRO from S0 (clean): onboard → Планы → «Выбрать курс на Главной» → «Откройте план дня».
- EVIDENCE: `B-fresh-clean/artifacts/J1-plans-empty.png`, `J1-cta-loop-home.png`, `J1-plan-of-day-loop.png`, `EMPTY-light-E1.png`, `EMPTY-dark-E1.png`, `trace-J1.log` 06:40:30–06:40:32.
- ROOT CAUSE (confirmed): `webapp-frontend/src/DashboardScreen.tsx:856-866` (CTA only calls `onOpenHome`); `HomeScreen.tsx:420-422`. Spec premise
  `docs/PROJECT_SPEC.md:695-696` («переход на «Главную» с каталогом программ») assumes FD-01 does not occur.
- LIKELY LAYER: UX dead-end (root: missing system content).
- SOURCES: F-B-FRESH-CLEAN-02. **LOCAL only.**

### FD-04 [P1] Custom-workout path on an empty library has no discoverable first exercise, and a 0-exercise workout gives no way forward
- REFERENCE BEHAVIOR: picker = search + alphabetical list, with a no-match row "Create Exercise: <query>" (OBS). Library size on a clean account is UNK.
- OUR BEHAVIOR: clean picker shows only the hint and «Ничего не найдено»; «Создать своё» appears only after typing. On the workout detail with 0
  exercises: chip «Пока без упражнений», «Начать» **disabled with no explanation**, «Упражнения | В тренировке пока нет упражнений» with no CTA;
  «Добавить в план» is enabled and then fails with «Не удалось добавить: У выбранной тренировки нет упражнений» (422); the only exit is «Изменить».
- FIRST DIVERGENCE: J2 step "add first exercise" (clean); J3 zero-exercise variant (both installs).
- USER IMPACT: matches the owner's real-device report "custom workout reached 'no exercises' with no way forward". Emulation shows a soft dead
  end (typing or «Изменить» works), but on a clean install this is the only path to any workout.
- SEVERITY: **P1 while the library is empty** (model: "custom workout cannot get an exercise"). The explorers suggested P2 (F-04) and P3 (F-07);
  I raise it, because together with FD-01 the first exercise is undiscoverable and the owner reproduced it on a device. It becomes P2 once FD-01/FD-07 ship a library.
- REPRO from S0 (clean): onboard → «Своя программа» → name → «Создать и добавить упражнения» → «+ Добавить упражнение» (observe) → back without
  typing → «Сохранить» → detail.
- EVIDENCE: `B-fresh-clean/artifacts/J2-picker-empty.png`, `EMPTY-light-E4.png`, `EMPTY-dark-E4.png`, `E12-detail.png`, `E12-addtoplan.png`,
  `E12-record-empty-saved.png`, `EMPTY-dark-E12-detail.png`; `B-fresh-catalog/artifacts/j3-01-empty-detail.png`, `j3-01-empty-in-plan.png`.
- ROOT CAUSE: confirmed by observation. Code not pinned beyond the explorers' testid (`workout-detail-start` disabled). The content side is FD-01 / FD-07.
- LIKELY LAYER: UX dead-end (with missing system content).
- SOURCES: F-B-FRESH-CLEAN-04, F-B-FRESH-CLEAN-07, F-B-fresh-catalog-07. **LOCAL only.**

### FD-05 [P1] An expired user can start and complete course sessions; the v2 live path has no subscription check
- REFERENCE BEHAVIOR: Crimpd+ upsell exists (OBS); gating is UNK. **Spec rule:** `docs/plan-and-specs.md:339-341` (§14 default, in force per
  §16:364): after the trial, courses in the plan are paused and «Начать» → subscription screen. Free workouts stay free.
- OUR BEHAVIOR: Планы shows the banner «Нет активной подписки. Оформи её в боте, потом возвращайся сюда.» but «Начать» stays enabled. Pre-screen
  «ГОТОВЫ К СТАРТУ» → Live → 2 sets → «Тренировка завершена». The session is saved («1 из 3», Журнал after reload).
- FIRST DIVERGENCE: J6, audit_expired, Планы → «Начать».
- USER IMPACT: the paywall is bypassed for the paid content (revenue), and the surfaces contradict each other: the banner says no access and the button works.
  The legacy screens (WorkoutScreen/BackdateForm) do block with the same text, which is a likely source of the owner's "no_access" confusion.
- SEVERITY: **P1** (subscription/auth defect). C suggested P1. B-clean F-05 suggested P2 / "maybe domain"; I **split** that finding. For a custom/free workout
  the expired user is **allowed by §14**, so that part is not a defect. The course start is the defect. Needs owner confirmation of §14 (decision D6).
- REPRO from S0: profile audit_expired (tg 7300006: trial ended 2026-09-09, cache `trial`) → Планы → «Начать» → «Начать» → «Готов» → 10 →
  «Готово» ×2 → «Завершить» → «3» → «Сохранить и завершить». A real user reaches this state by simply letting the trial end.
- EVIDENCE: `C-existing/artifacts/J6_audit_expired.trace.txt` (06:49:41 "FAIL F-C-02", 06:49:54), `J6_audit_expired__02_plans_expired.png`,
  `J6_audit_expired__03_after_expired_train.png`; `B-fresh-clean/artifacts/J6-expired-*.png`, `trace-J6.log`.
- ROOT CAUSE (confirmed):
  - `app/web/routes_v2.py:1584-1608` `start_live_session` and `LiveSessionService.start_session` call no `SubscriptionService.has_access`.
    `has_access` is used only in legacy `app/web/routes.py:736-737`, `:1710-1711`.
  - The banner comes from the legacy readiness status rendered through `STATUS_MESSAGES` (`webapp-frontend/src/DashboardScreen.tsx:707-713`;
    text at `WorkoutScreen.tsx:55`); it does not disable the button.
  - No admin bypass in `has_access` (`app/services/subscription.py:104-106`).
- LIKELY LAYER: subscription/auth defect.
- SOURCES: F-C-02, F-B-FRESH-CLEAN-05 (course part). **LOCAL only.**

### P2 defects

| FD | Title | REFERENCE | OUR BEHAVIOR (verbatim) | FIRST DIVERGENCE | USER IMPACT | REPRO from S0 | EVIDENCE | ROOT CAUSE / LAYER | SOURCES |
|---|---|---|---|---|---|---|---|---|---|
| FD-06 | Catalogue scripts are not part of deploy; `seed_exercise_library.py` crashes as documented; docs disagree on `scripts/` in the image | content ships with the product (INF) | `python scripts/seed_exercise_library.py` → `sqlalchemy.exc.NoReferencedTableError: Foreign key associated with column 'exercises.owner_user_id' could not find table 'users'` | operator step 3 of the catalogue install | the only delivery path for FD-01 content is manual and partly broken | `BOT_TOKEN=x DATABASE_URL=… python scripts/seed_exercise_library.py` | `B-fresh-catalog/artifacts/seed_exercise_library_standalone_error.txt`; C PROFILES step 4 | `scripts/seed_exercise_library.py:15-16` imports only `models_program`; `deploy/deploy-run.sh:32-38`; `Dockerfile:11` vs `.claude/skills/deploy-and-verify/SKILL.md:43-48`. `seed_collections.py` has the same import pattern (INFERRED, untested). Layer: seed/test illusion | F-B-fresh-catalog-10, F-C-17 (+ Judge) |
| FD-07 | Even with the scripts the catalogue is thin and partly internal: 1 program, no pull-up library exercise, «Факультатив — …» internal exercises in the picker, published collection empty/hidden | catalogue + library (OBS / INF) | picker: «Факультатив — подтягивания на максимум / W / 3 минуты подтягиваний / на объём», «Планка», «Отжимания»; search «подтягивания» → only «Факультатив …»; Home: no collection row | J2 picker; J1 "every program" | a custom pull-up workout starts from nothing useful; internal items confuse | catalogue install → «Создать тренировку» → «+ Добавить упражнение» | `B-fresh-catalog/artifacts/j2-01-picker.png`, `j2-01-search-aus.png`, `onb-02-reload.png`, PROFILES.md | missing system content (owner decisions D1–D3); collection items need `seed_collections.py` (`9e3f1a4b6c80_collections.py:18-23`) | F-B-fresh-catalog-03, -11, -13 |
| FD-08 | Future weeks of a course plan look empty; copy week «Скопировано: 0»; › silently creates empty weeks | UNK (E10/E11) | «Неделя 2 · 12 окт – 18 окт | 0 из 0 | На эту неделю пока ничего не запланировано.»; «Скопировано: 0, пропущено дублей: 0» | J4 › on a course plan | "plan with zero workouts" when browsing ahead; no explanation that course sessions appear when the week starts | catalogue: add «Подтягивания» → Планы → › | `B-fresh-catalog/artifacts/j4-01-next-week.png`, `j4-01-after-confirm-copy.png`, `j4-01-week3.png`, `j4.log` | **specified behaviour** (`docs/PROJECT_SPEC.md:677-680,684-685`; `app/services/plan_week.py:121-126,144-150`); rollover verified working (C J1 week transition). Layer: valid domain difference + UX gap (not a plan-generation defect) | F-B-fresh-catalog-08, -09 |
| FD-09 | Strength block: Program Detail and pre-screen promise 4 sets, Live gives 1 | — | pre «ЦЕЛЬ 2: 3 ПОВТОРЕНИЙ / 4 рабочих подхода»; Live «1 / 1 … Подход 1/1»; C summary «— 0/1» | J1 Live block Б | half of the course runs at ¼ of the promised volume; existing (bot-era 4-set) users silently change regime | catalogue J1 or any C profile → Начать | `B-fresh-catalog/artifacts/j1-01-stuck8.png`, `j1-01-summary.png`; C TRACE J1 | `app/services/live_session.py:441` `role_state.get("work_sets", 1)`; block_b state has no `work_sets` (`app/services/program_inclusion.py` progression_state block_b) although config has `STRENGTH_BLOCK.work_sets` (backfill `_program_config_snapshot`). Needs a progression plan per CLAUDE.md. Layer: legacy/v2 convergence | F-B-fresh-catalog-02, C observation |
| FD-10 | Pre-start target ≠ Live target for returning (gap) users | — | pre «Цель 1: 9 повторений · 3 рабочих подхода»; Live «Подход 1/3 · Цель: 11 повт. 3×11» | J6 expired / gap profiles | the user is promised one target and executes another | audit_expired_b → Планы → Начать | `C-existing/artifacts/J6_audit_expired.trace.txt` 06:39:49-53, `J6_audit_expired_b.trace.txt` | pre-screen reads `/api/v2/dashboard/status` (gap rollback, `SessionPreScreen.tsx:114`); Live uses the frozen `progression_state`. Layer: legacy/v2 convergence | F-C-03 |
| FD-11 | Subscription surfaces inconsistent: stale «пробный период (осталось 0 дн.)»; no pay action in the Mini App | INF upsell | «Подписка : пробный период (осталось 0 дн., до 09.09.2026)» while Планы says «Нет активной подписки…»; Подписка: «Оплата картой временно недоступна.», «Как оформить: оплата прямо в боте…», no button | J6 Профиль | the user cannot tell their status or how to pay from the Mini App | expire trial (clean injection or C audit_expired) → Профиль → Подписка | `B-fresh-clean/artifacts/J6-expired-subscription.png`, `trace-J6.log`; `C-existing/artifacts/J6_audit_expired__01_profile_expired.png` | `app/services/subscription.py:89-102` lazy `refresh_status`; `GET /api/profile` does not refresh (`app/web/routes.py:488` per B-clean). "Оплата картой временно недоступна" may be env config (Robokassa creds absent locally): UNKNOWN on staging. Layer: subscription/auth | F-B-FRESH-CLEAN-05 (pay part), -08, F-C-18 |
| FD-12 | Removing a manual plan row rewrites Журнал history (title becomes «Тренировка») | INF history survives | «По плану | Мои подтягивания» → «По плану | Тренировка»; Планка run → «Тренировка» | J2/J4 after «Убрать из плана» | history display data lost, against the endpoint docstring «Journal history не задеты» and constitution V | plan-run a workout → «Действия» → «Убрать из плана» → Журнал | `B-fresh-clean/artifacts/J2-journal-plan.png` vs `J2-journal-after-remove.png`; B-catalog TRACE 06:14:44 | `app/db/repositories/training_plans.py:250-262` deletes the PlanItem; `session_plan_items` FK `ondelete="CASCADE"` (`app/db/models_program.py:455`); `_resolve_session_titles` (`app/web/routes_v2.py:1104`) reads the title through it. Layer: persistence defect | F-B-FRESH-CLEAN-06, F-B-fresh-catalog-06 (title part) |
| FD-13 | Deleting or editing a legacy workout does not change Аналитика | OBS recompute on add/delete (A8) | Журнал entry gone; «Тренировок за 30 дней» 5 → 5 | J5b delete | analytics diverge from the journal for every migrated user | audit_legacy_existing → Журнал → legacy 02.10 → «Удалить» → Аналитика | `C-existing/artifacts/J5b_audit_legacy_existing.trace.txt`, `…__j5b_03_final.png` | `app/services/training_analytics.py:72` `list_all_completed(user_id)` without `exclude_backfilled`; `app/services/workout_deletion.py:33,59` do not touch the backfilled `training_sessions` copy (the Journal hides copies: `routes_v2.py:1280`). Layer: legacy/v2 convergence | F-C-14 |
| FD-14 | A completed native plan session in Журнал cannot be edited/cloned/deleted, with no explanation | OBS View/Edit/Clone/Delete | sheet «Открыть / Отмена» only; detail read-only | J5a | a wrongly logged rep count cannot be fixed | J1 session → Журнал → tap | `C-existing/artifacts/J5a_audit_existing_active__j5a_01_native_sheet.png`, `__j5a_02_native_detail.png` | deliberate `REASON_PROGRAM` in `app/services/session_deletion.py::_verdict`; the defect is the missing reason/alternative. Layer: UX dead-end | F-C-05 |
| FD-15 | Activity «Повторить» creates a different, mislabelled entry | OBS Clone (form UNK) | «Записана задним числом | Тренировка | Подходы — | Повторы — | Усилие 2»; Аналитика «Без категории» | J5a clone | wrong history and analytics | backdate «Плавание 0:40» → «Повторить» → «Создать копию» | `C-existing/artifacts/J5a_…__j5a_04_clone.png`, `__j5a_05_final.png` | clone `app/web/routes_v2.py:1367` → `SessionEditingService.clone` does not copy `activity_type`/`duration_seconds`. Layer: API/backend | F-C-09 |
| FD-16 | Summary/detail lose block names | OBS review sheet set table | summary «— 3/3 , выполнено», «Новая цель 10 → 10 / 3 → 3» unlabeled; detail cards «Упражнение» | J1 summary, J5 detail | the user cannot tell which block is which | catalogue J1 → finish | `B-fresh-catalog/artifacts/j1-01-summary.png`; `C-existing/artifacts/J5a_…__j5a_02_native_detail.png` | `app/web/routes_v2.py:286` `_catalog_exercise_names` drops role exercise names. Layer: API/frontend | F-B-fresh-catalog-04, F-C-06 |
| FD-17 | Onboarding baseline is not used for the course's starting target (8 reps → 3×10) | — | «старт: 10 повт. × 3 подх.», Live «Цель: 10 повт.» | J1 Program Detail | a new user with a max of 8 is asked for 3×10 | onboard with 8 → add the course | `B-fresh-catalog/artifacts/j1-02-program-detail.png`, `j1-01-live-1.png` | `app/services/program_inclusion.py` uses `request.initial_target_*` or config `base_target`; the UI sends none. Product decision (progression change → plan first). Layer: UNKNOWN / valid domain? | F-B-fresh-catalog-14 |
| FD-18 | «Начать» on a too-early day leads to a text dead end with no earliest date | — | Планы «Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл.» + enabled «Начать» → «ТРЕНИРОВКА … Перейти в обычную "Тренировку"» | J6 audit_trial | a frequent trainer "cannot start any workout" and is not told when they can | audit_trial (trained yesterday) → Планы → Начать | `C-existing/artifacts/J6_audit_trial.trace.txt`, `J6_audit_trial__profile.png` | domain rule valid (MIN_REST_DAYS); UX dead-end. The target of «Перейти в обычную "Тренировку"» is UNTESTED. Raised from P3: candidate for the owner's symptom | F-C-19 |

### P3 defects

| FD | Title | OUR BEHAVIOR (verbatim) | Evidence | Layer | Sources |
|---|---|---|---|---|---|
| FD-19 | Raw internal identifiers, fractional tallies, minutes 0 | «pull_ups», «PULL_UPS», «user», «block_a 3.5», «elective_max_reps_ladder», «Итого 7 0» | `B-fresh-catalog/artifacts/onb-02-reload.png`, `j1-02-analytics.png`; `C-existing/artifacts/J1_audit_existing_active__09_analytics.png`; `B-fresh-clean/artifacts/J2-analytics.png` | UX / localisation | F-B-fresh-catalog-05, -06 (minutes), F-C-20, F-B-FRESH-CLEAN-09 |
| FD-20 | Internal jargon in the free-workout summary | «Прогрессия не пересчитана — нет активного курса со ступенчатой стратегией для этих упражнений.» | `B-fresh-clean/artifacts/J2-summary-plan.png` | UX copy | F-B-FRESH-CLEAN-10 |
| FD-21 | Completion semantics: a partial run is counted «1/1 · Ещё раз»; re-adding a course resets «0 из 3» | «Что сделано — зачтено, остальное останется в плане.» then «1/1» | `B-fresh-clean/artifacts/after-close-summary.png`, `plans-after-complete.png` | UNKNOWN (domain question) | F-B-FRESH-CLEAN-11, F-B-fresh-catalog-12 |
| FD-22 | Contradictory Планы card above a week with manual rows | «Курсов в плане нет. Добавьте курс на Главной.» + CTA above «ЧЕТВЕРГ | Мои подтягивания» | `B-fresh-clean/artifacts/J4-plan-week2.png` | UX copy | F-B-FRESH-CLEAN-12 |
| FD-23 | «Создать своё» persists the exercise before the protocol is confirmed | `POST /api/v2/exercises` on tap; «Отмена» leaves it in the library | B-clean TRACE exploration notes | persistence | F-B-FRESH-CLEAN-13 |
| FD-24 | Activity edit form cannot change duration/type | «Изменить тренировку | ДАТА | КАК ПРОШЛА ТРЕНИРОВКА? | КОММЕНТАРИЙ» | `C-existing/artifacts/J5a_…__j5a_03_edit_form.png` | UX | F-C-08 |
| FD-25 | After a reopen mid-rest, the logged-set chip and «Изменить» are gone (data kept) | «ОТДЫХ | 1:25 | Пропустить отдых» without «Подход 1: 10 повт.» | `C-existing/artifacts/J7_audit_persist.trace.txt` | execution/live-session | F-C-15 |
| FD-26 | Backfilled elective shows «Подходы 1» for a 4-set ladder | «Факультатив — подтягивания на максимум | Подходы 1 | Повторы 36» | `C-existing/artifacts/J5b_…__j5b_02_prev_week.png` | legacy/v2 convergence | F-C-16 |

Non-defects (harness/platform): F-B-FRESH-CLEAN-14 (Playwright build mismatch); console «Telegram SDK init() failed … launch parameters» (mock artefact, all roles); the B-catalog dark pass is invalid; Program Detail's «‹» has no accessible name (noted by B-catalog, not scored).

### Source → FD map

| Explorer id | FD | Explorer id | FD | Explorer id | FD |
|---|---|---|---|---|---|
| F-B-FRESH-CLEAN-01 | FD-01 | F-B-fresh-catalog-01 | FD-02 | F-C-02 | FD-05 |
| -02 | FD-03 | -02 | FD-09 | F-C-03 | FD-10 |
| -03 | FD-02 | -03 | FD-07 | F-C-05 | FD-14 |
| -04 | FD-04 | -04 | FD-16 | F-C-06 | FD-16 |
| -05 | FD-05 (course) / FD-11 (pay) / not a defect (free) | -05 | FD-19 | F-C-08 | FD-24 |
| -06 | FD-12 | -06 | FD-12 / FD-19 | F-C-09 | FD-15 |
| -07 | FD-04 | -07 | FD-04 | F-C-14 | FD-13 |
| -08 | FD-11 | -08 | FD-08 | F-C-15 | FD-25 |
| -09 | FD-19 | -09 | FD-08 | F-C-16 | FD-26 |
| -10 | FD-20 | -10 | FD-06 | F-C-17 | FD-06 |
| -11 | FD-21 | -11 | FD-07 | F-C-18 | FD-11 |
| -12 | FD-22 | -12 | FD-21 | F-C-19 | FD-18 |
| -13 | FD-23 | -13 | FD-07 | F-C-20 | FD-19 |
| -14 | harness | -14 | FD-17 | | |

---

## 7. Owner symptoms → defects

| Owner symptom (real iPhone) | Defects | Confidence | What confirms it on staging (read-only) |
|---|---|---|---|
| "Could not start any workout" | FD-01 (no course to start, if staging lacks the catalogue); FD-04 (custom workout without exercises: «Начать» disabled); FD-02 (added a workout, nothing to start); FD-18 (too-early text dead end for a frequent trainer) | **medium**. Which one applies depends on staging content and the owner's last session date | `SYSTEM_CONTENT_CONTRACT.md` §4 counts; `SELECT max(performed_at) FROM training_sessions WHERE user_id=<owner>`; owner's `plan_items` with `plan_week_id IS NULL`; owner's `complexes` with 0 `complex_items` |
| "Sometimes no plan" | FD-03 (E1 loop when the catalogue is empty); E1 for users onboarded after the backfill run (backfill enrols only users that existed at run time); course removal leaves «0 из 0» (by design) | medium | `SELECT u.telegram_id FROM users u LEFT JOIN training_plans p ON p.user_id=u.id WHERE p.id IS NULL AND u.onboarding_completed_at IS NOT NULL`; programs count |
| "Adding a plan → a plan with zero workouts" | **FD-02** (first add orphaned); FD-08 (week ≥2 of a course is empty) | **high** for FD-02 (deterministic repro on both installs); medium for FD-08 | `SELECT count(*) FROM plan_items WHERE plan_week_id IS NULL AND program_inclusion_id IS NULL` > 0 confirms FD-02 |
| "Custom workout reached 'no exercises' with no way forward" | **FD-04**, with FD-01 / FD-07 (empty or only «Факультатив» library) | **high** | `exercises_public_library` = 0 or only internal rows (§4 query) |
| "Recent no_access case" | FD-05 / FD-11: banner «Нет активной подписки. Оформи её в боте, потом возвращайся сюда.» for any user past `subscription_expires_at` (cache still `trial`); legacy WorkoutScreen/BackdateForm block with the same text; no admin bypass in `has_access` | **high** that the text is this one; medium on which screen | `SELECT subscription_status, subscription_expires_at FROM users WHERE telegram_id=<owner>`; whether the owner id is in `ADMIN_IDS` |

## 8. System content findings (summary)

Full contract: `docs/SYSTEM_CONTENT_CONTRACT.md`.
- Migrations ship protocols (3) and one empty collection. Programs, exercises and workouts ship only through manual scripts.
- `backfill_multi_program.py` is **not** a safe catalogue seed: a non-dry run also enrols every onboarded user without a TrainingPlan into «Подтягивания»,
  and `--dry-run` skips `seed_catalog`.
- `seed_exercise_library.py` crashes standalone (FD-06). `seed_collections.py` has never been run by the audit.
- Even with all scripts there is no public pull-up exercise and no system workout (FD-07, owner decisions D1/D2).
- Indirect evidence that the backfill ran on the owner's environment: #279, #282 and #284 fixed artefacts of backfilled history that the owner saw
  (`docs/ENGINEERING_NOTES.md:2576-2581`; commits `a2b35f1`, `a212f4e`, `bcb26fa`). Whether `seed_exercise_library` / `seed_collections` ran is UNKNOWN.

## 9. False-confidence audit (§19)

Seed census (`scripts/e2e_seed.py`, AST closure over each `SCENARIOS` entry, 41 scenarios):
- **6** call `seed_exercise_library`: sweep_populated, plan_week_add_exercise, plan_week_manual_session, journal_combined, plan_week_stepper, plans_overview.
- **13** create `Program` rows (find-or-create global, or per run): first_workout, sweep_populated, collections, home_discovery,
  v2_session_ready, v2_session_complex, v2_session_progression_edit, plan_week_ready, plan_week_grouping, plan_week_add_exercise,
  plan_week_start_session, journal_combined, plans_overview.
- **15** distinct scenarios inject system content that production lacks.
- **20** pre-create TrainingPlan / PlanWeek / PlanItem / inclusions.
- All of them run into **one shared CI database** (`scripts/e2e_seed_all.sh`). The first line seeds `first_workout`, which creates the global program
  «Первая тренировка», so every spec, the "empty" ones included, runs with a non-empty catalogue.

| Defect | OLD TEST THAT CLAIMED COVERAGE | WHY IT PASSED | WHAT A NEW TEST MUST PROVE (layer) |
|---|---|---|---|
| FD-01 | `first-workout.spec.ts` ("первая тренировка: курс из каталога → в план…") | **catalogue created by the seed**: `seed_first_workout` creates «Первая тренировка» (`e2e_seed.py:163-195`). Impossible prod fixture | deploy/integration: a DB built exactly like deploy (empty DB → `alembic upgrade head` → the chosen content mechanism, **no e2e seeds**) returns `GET /api/v2/programs` ≥1 and the agreed library. Then a Playwright J1 from S0 on that DB with UI onboarding |
| FD-01 | `golden-journey.spec.ts:31` `.program-card-button.first()` | depends on programs created by **other** seeds in the shared DB (`golden_journey` seeds none); order-dependent | same as above; golden journey must start from UI onboarding on the content-only DB |
| FD-01 | `parity/full-sweep.spec.ts` "empty" mode; seeds `sweep_empty` / `home_workouts` | false premise in docstrings: «каталог программ глобальный и приходит из миграций» (`e2e_seed.py:1462-1463`), «Каталог Программ приходит из миграций» (`:1240`). The empty user's flow opens «Свип: курс», which the **populated** seed created (`:1498-1503`) | an "empty" user must mean an empty user on a content-only install; assert the Home catalogue comes from shipped content (by name), not from e2e programs |
| FD-01 | `home-discovery.spec.ts` | seed creates 3 programs (`e2e_seed.py:1270-1290`) | as above |
| FD-02 | `golden-journey.spec.ts` (Мою тренировку в план → «Свободный пул» → «Добавить» → row visible) | **preseeded TrainingPlan + current PlanWeek** (`seed_golden_journey`, `e2e_seed.py:1332-1340`), so `AddToPlanScreen` gets a week id; never reloads | e2e from S0 with **no TrainingPlan row**: first add → reload → row in the current week. Backend: `POST /plan-items` without `plan_week_id` for a user without a plan attaches to the current week (or rejects); DB invariant: no manual `plan_items.plan_week_id IS NULL` |
| FD-02 | `tests/test_web/test_v2_plan_items_with_week.py:131-147` | **codifies the defect** (asserts `plan_week_id is None` as "старое поведение") | replace with a test asserting the item appears in `GET /api/v2/plan` within `current_week_id` |
| FD-02 | `parity/plans-current-week.spec.ts`, `session-recovery.spec.ts`, `collections.spec.ts`, builder-* (`builder_workouts`) | preseeded plan/week; `collections.spec.ts:127-131` only opens the sheet | — |
| FD-02 | `parity/full-sweep.spec.ts` flow "Деталь → Добавить в план" (`:283-285`) | **bypassed creation**: asserts only that the «Добавить» button is visible; never submits | — |
| FD-03 | `parity/full-sweep.spec.ts` D3 (`:519-526`) "Планы без курсов: … с кнопкой-переходом" | **screen text only**: asserts `plans-now-card` has ≥1 button; never taps, never checks that the destination is actionable; and the catalogue is never empty in CI | journey-level: on an empty catalogue (and on a catalogue fetch error) E1's CTA leads to an actionable state (course card or «Создать тренировку») within ≤2 taps |
| FD-04 | `builder-ux.spec.ts`, `builder-execution.spec.ts`, `home-discovery.spec.ts` | users have seeded own exercises/workouts (`builder_workouts`, `home_workouts` create user Exercises); the picker is never empty | e2e on a content-only install: a new user creates a workout and adds a first exercise **without typing** (visible create/choose CTA); the zero-exercise detail shows a reason and a CTA |
| FD-05 | `tests/test_web/test_workout.py:150` `test_plan_without_subscription_is_no_access`, `test_backdate.py:112` | **wrong lifecycle**: they test legacy `/api/workout/plan` and backdate, which the v2 start path does not use. **No e2e seed creates an expired user** | backend: `POST /api/v2/sessions/live` with program-backed `plan_item_ids` for a user past `subscription_expires_at` (cache still `trial`) → refused (e.g. 402/403 `no_access`); free workout still allowed (§14). e2e: expired user → Планы → «Начать» → subscription screen; reload |
| FD-06 | `tests/test_web/test_v2_exercises.py` | imports `app.db.models` (`:24`) before `scripts.seed_exercise_library` (`:27`) and calls the function, never `main()` in a fresh interpreter | subprocess test: run each content script exactly as documented (`python scripts/<x>.py --dry-run` then real) in a clean interpreter against a migrated DB; exit 0 |

Root pattern: tests prove **screens given data**, never **the data's provenance**. Content, plan and week are injected by direct ORM setup. Specs rarely reload after a mutation.
The suite has no "fresh install" profile and no "expired" profile.

---

## 10. Ranked fix plan (dependency order)

| Order | Stage | Items | Depends on |
|---|---|---|---|
| 1 | System catalogue/content | **FD-01**, **FD-06**, FD-07 (after owner decisions D1–D4) | owner decisions |
| 2 | Program → plan generation | FD-08 (explain or preview future course weeks), FD-17 (decision), FD-09 (decision + plan per CLAUDE.md) | 1 |
| 3 | Plan → actionable workout / add-to-plan | **FD-02**, **FD-03**, FD-22 | FD-03 partly 1 |
| 4 | Custom workout → exercise | **FD-04**, FD-23 | 1 helps (library) but is independent |
| 5 | Workout → live | **FD-05** (after D6), FD-18, FD-10 | — |
| 6 | Live → complete | FD-09, FD-16, FD-21, FD-20 | 2 |
| 7 | Complete → journal | FD-12, FD-14, FD-15, FD-24, FD-26 | — |
| 8 | Journal → analytics | FD-13, FD-19 | — |
| 9 | Persistence / recovery | FD-25, FD-11 (status refresh) | — |

### Fix Wave 1: 4 independent items

| Item | Scope | Re-audit that converts FAIL → PASS (from S0) |
|---|---|---|
| **W1-A** System content ships with deploy (FD-01 + FD-06) | mechanism per `SYSTEM_CONTENT_CONTRACT.md` §5 (recommended: data migration for the minimum); fix the script import; e2e seeds stop creating programs and library exercises | **B-fresh-clean J1** on an empty DB → `alembic upgrade head` (+ the chosen step) → UI onboarding → Главная shows the course → «Добавить в план» → Планы row → Начать → Live → finish → Журнал → Аналитика → reload. Also E1 resolves |
| **W1-B** First add-to-plan attaches to the current week (FD-02) | backend default to the current week when `plan_week_id` is absent (or frontend refetches after lazy plan creation); attach or archive existing orphans (constitution V) | **B-fresh-clean J2b / J4** and **B-fresh-catalog J2 / search**: S0 (no plan) → first «Добавить в план» (workout and exercise) → reload → row visible in «Текущая неделя · 0 из 1» → «Начать» |
| **W1-C** Empty-state fallbacks for the custom path (FD-03 + FD-04) | E1 offers «Создать тренировку» alongside the course CTA; picker empty state shows a visible create CTA; zero-exercise detail explains the disabled «Начать» and offers «Добавить упражнение»; validate before «Добавить в план» | **B-fresh-clean J2 and E1/E4/E12** on a clean install: no typing-only affordance, no loop, every CTA reaches an actionable state |
| **W1-D** Subscription gating on v2 per §14 (FD-05), after the owner confirms D6 | `has_access` on program-backed live start (and inclusion creation, if confirmed); UI: «Начать» → subscription screen with an actionable CTA; free workouts stay open | **C J6** audit_expired / _b: Планы → «Начать» → subscription screen; free workout still starts; after the admin grant the course starts; reload at each step |

## 11. Where the Judge disagreed with the explorers

1. F-B-FRESH-CLEAN-02 (P0 → **P1**, FD-03) and F-B-FRESH-CLEAN-03 (P0 → **P1**, FD-02): neither makes all training impossible; the root P0 is FD-01.
2. F-B-FRESH-CLEAN-04 (P2) and -07 / F-B-fresh-catalog-07 (P3) → **P1** (FD-04) while the library is empty: it matches the owner's device report and is the only path on a clean install.
3. F-B-FRESH-CLEAN-05 split: a custom/free workout for an expired user is **allowed** by `plan-and-specs.md` §14. Only the course start is a defect (FD-05, P1); the pay action belongs to FD-11.
4. F-B-fresh-catalog-08 ("plan-generation defect"): **not a generation defect**. Course rows are materialised only for the current week by spec (`PROJECT_SPEC.md:677-680`), and rollover works (C). Reclassified as UX (FD-08, P2).
5. F-C-19 (P3 → **P2**, FD-18): an owner-symptom candidate.
6. F-C-17 (P3) aligned with F-B-fresh-catalog-10 (P2) → **P2** (FD-06), because it is the delivery path of P0 content.
7. Director brief: `scripts/` **is** in the `app` image (`Dockerfile:11`). The blocker is that deploy never runs the scripts, and that backfill is unsafe as a seed.
8. C-existing's "not reproduced" for the owner symptoms holds only for backfilled users. New users after the backfill run have no plan and fall into E1.
