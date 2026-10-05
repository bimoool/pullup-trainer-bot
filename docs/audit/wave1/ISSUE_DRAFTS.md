**Filed issues (P0/P1):** FD-01 → #296 · FD-02 → #297 · FD-03 → #298 · FD-04 → #299 · FD-05 → #300 (sub-issues of umbrella #295). P2/P3 stay in the backlog in `docs/audit/wave1/ISSUE_DRAFTS.md`.

# Issue drafts: Functional Differential Audit Wave 1 (#295)

These are drafts for the Director to file. They are not filed yet. Each draft has a single acceptance criterion: a journey re-audit from S0 that ends in PASS
(PASS = visible after a UI action, survives a reload, and enables the next action; an HTTP 200 or a DB row alone does not count).
Full context: `docs/FUNCTIONAL_AUDIT_WAVE_1.md`. Content contract: `docs/SYSTEM_CONTENT_CONTRACT.md`. All findings are LOCAL only.

---

## [FUNC-AUDIT P0] Clean install ships no training catalogue: course path impossible for every fresh user (FD-01, incl. FD-06)

**Repro from S0**
1. Empty Postgres → `alembic upgrade head` (exactly what `deploy/deploy-run.sh:37` does). Nothing else.
2. Open the Mini App as a new Telegram user → complete onboarding (Замер → Анкета → «Готово»).
3. Главная.

**Expected**: at least one course card (e.g. «Подтягивания») that leads to Program Detail → «Добавить в план». The exercise picker offers library exercises.
**Actual**: «Каталог курсов появится здесь позже.». `GET /api/v2/programs` → `{"programs":[]}` and `GET /api/v2/exercises` → `{"exercises":[]}`. DB: programs=0,
exercises=0, complexes=0; only 3 assessment_protocols and 1 collection with 0 items.

**Evidence**: `docs/audit/wave1/B-fresh-clean/artifacts/J1-home-catalogue.png`, `after-onb.png`, `api-programs.json`, `api-exercises.json`, `trace-J1.log`;
script crash `docs/audit/wave1/B-fresh-catalog/artifacts/seed_exercise_library_standalone_error.txt`.

**Root cause (confirmed)**
- No migration inserts programs or exercises. Catalogue content exists only in `scripts/backfill_multi_program.py::seed_catalog` (`:245-290`) and
  `scripts/seed_exercise_library.py`. `deploy/deploy-run.sh:32-38` never runs them.
- `backfill_multi_program.py` is unsafe as a seed: a re-run enrols every onboarded user without a plan into «Подтягивания», and `--dry-run` skips seeding.
- `seed_exercise_library.py:15-16` crashes standalone (`NoReferencedTableError exercises.owner_user_id → users`; only `models_program` is imported).
- `scripts/` is in the `app` image (`Dockerfile:11`) but not in the `web` image. `.claude/skills/deploy-and-verify/SKILL.md:43-48` and CLAUDE.md say otherwise (stale).
- e2e seeds create programs and library exercises themselves (15 of 41 scenarios), so CI never saw an empty catalogue.

**Likely layer**: missing system content + seed/test illusion.

**Scope** (after owner decisions D1–D4 in `SYSTEM_CONTENT_CONTRACT.md` §6): deliver the minimum content of contract §3 through the chosen mechanism (recommended:
an additive, idempotent data migration). Make the content scripts runnable as documented. Stop `scripts/e2e_seed.py` from creating programs and library
exercises (or assert that it is a no-op on top of the shipped content). Fix the stale docs. Add a deploy-level test: an empty DB at `head` with no seeds
returns ≥1 program and the agreed library.

**Acceptance (journey re-audit from S0)**: rerun **B-fresh-clean J1** on an empty DB built only by the deploy steps → UI onboarding → Главная shows the course →
Program Detail → «Добавить в план» → Планы shows an actionable row → «Начать» → Live → «Завершить» → summary → Журнал → Аналитика → reload, and a new context
still shows it. Also E1 (Планы → «Выбрать курс на Главной») reaches the course.

**Dependencies**: owner decisions D1–D4. Unblocks FD-03 (the loop disappears) and lowers FD-04 to P2. Independent of FD-02 and FD-05.

---

## [FUNC-AUDIT P1] First «Добавить в план» from a user without a plan is stored with plan_week_id=NULL and never shown (FD-02)

**Repro from S0** (either install; user onboarded, no TrainingPlan row)
1. Главная → «Создать тренировку» → name → «+ Добавить упражнение» → «Создать своё: «X»» → «Добавить» → «Сохранить».
2. «Добавить в план» → «Ср» → «Добавить».
3. Reload → Планы.
(Catalogue install alternative: Главная search «Планка» → «Добавить в план» → «Пн» → «Добавить».)

**Expected**: «Текущая неделя · 0 из 1 | СРЕДА | X | 0/1 | Начать».
**Actual**: «Текущая неделя · 0 из 0 | На эту неделю пока ничего не запланировано.» No error is shown. A second add works and hides the problem. The first row is invisible and cannot be removed.

**Evidence**: `B-fresh-clean/artifacts/J2-plan-after-add.png`, `J4-plan-exists-week-0.png`, `api-plan-orphan.json`, `trace-J2.log` 06:44:48, `trace-J4.log` 06:45:57;
`B-fresh-catalog/artifacts/j2-01-after-add.png`, `j2-02-plans.png`, `search-01-after-add.png`, `search-02-plans.png`. Request body
`{"complex_id":2,"plan_week_id":null,"day_of_week":2,"count_per_week":1}` → 200.

**Root cause (confirmed)**
- `webapp-frontend/src/AddToPlanScreen.tsx:56-66` sets `planWeekId=null` when `fetchPlan` returns no plan; the value is sent at `:96`.
- `app/web/routes_v2.py:1002` lazily creates the plan; `:1025` validates the week only if one was given; `:1036-1040` stores NULL.
- `app/services/plan_week.py:88-94` attaches unweeked rows only for program inclusions.
- `webapp-frontend/src/DashboardScreen.tsx:973` filters rows by week.
- `tests/test_web/test_v2_plan_items_with_week.py:131-147` asserts the NULL behaviour.

**Likely layer**: API/backend defect + frontend state defect.

**Scope**: default a manual `POST /plan-items` without `plan_week_id` to the current week (via `ensure_current_plan_week`), or reject it, together with a frontend
refetch. Replace the codifying test. Handle the existing orphans by attaching them to the plan's current week or archiving them (constitution V; count them first:
`SELECT count(*) FROM plan_items WHERE plan_week_id IS NULL AND program_inclusion_id IS NULL`).

**Acceptance (journey re-audit from S0)**: **B-fresh-clean J2b + J4** and **B-fresh-catalog J2 + search-add**. A brand-new user with no plan makes a first add (both a workout and an
exercise) → reload → the row is in the current week → «Начать» → Live → finish → «1/1». DB invariant: zero manual rows with a NULL week.

**Dependencies**: none (independent of FD-01; reproducible on a clean install using an own exercise).

---

## [FUNC-AUDIT P1] Empty Планы CTA «Выбрать курс на Главной» loops with Главная «Откройте план дня» when there is no catalogue (FD-03)

**Repro from S0** (clean install): onboard → Планы → «Выбрать курс на Главной» → Главная («Каталог курсов появится здесь позже.») → «Откройте план дня» → Планы.

**Expected**: every empty-state CTA reaches an actionable state (a course, or create your own workout).
**Actual**: closed loop. Three taps, no state change, and Планы never offers «Создать тренировку».

**Evidence**: `B-fresh-clean/artifacts/J1-plans-empty.png`, `J1-cta-loop-home.png`, `J1-plan-of-day-loop.png`, `EMPTY-light-E1.png`, `EMPTY-dark-E1.png`, `trace-J1.log` 06:40:30–32.

**Root cause (confirmed)**: `webapp-frontend/src/DashboardScreen.tsx:856-866` (CTA only navigates Home); `webapp-frontend/src/HomeScreen.tsx:420-422`; the spec premise
`docs/PROJECT_SPEC.md:695-696` assumes a catalogue. The old e2e check `full-sweep.spec.ts:519-526` asserts only that a button exists.

**Likely layer**: UX dead-end (root: missing system content).

**Scope**: E1 and the empty Home catalogue offer the custom path («Создать тренировку» / «Своя программа») in addition to the course CTA. The «Откройте план дня» banner
must not lead to an empty Планы without an action. Cover the catalogue fetch-error state too.

**Acceptance (journey re-audit from S0)**: **B-fresh-clean J1/J4 E1** on a clean install, and also with the catalogue fetch failing: from Планы, every CTA reaches an actionable
screen in ≤2 taps; following it to a first completed workout → Журнал PASS.

**Dependencies**: FD-01 removes the common case; this draft stays for resilience. Independent of FD-02, FD-04 and FD-05. If FD-01 ships first, re-grade to P2.

---

## [FUNC-AUDIT P1] Custom workout on an empty library: no discoverable first exercise; 0-exercise workout «Начать» disabled with no reason (FD-04)

**Repro from S0** (clean install): onboard → «Своя программа» → name → «Создать и добавить упражнения» → «+ Добавить упражнение» (observe without typing) → back →
«Сохранить» → workout detail.

**Expected**: a visible way to choose or create the first exercise. On the empty-workout detail, an explanation and a CTA to add an exercise.
**Actual**: picker «Выберите упражнение — … Нет нужного? Введите название, и появится «Создать своё».» + «Ничего не найдено». The create CTA appears only after typing.
Detail «Пока без упражнений» / «В тренировке пока нет упражнений»; «Начать» disabled silently; «Добавить в план» enabled, then «Не удалось добавить: У выбранной тренировки
нет упражнений»; «Записать» → «Введи хотя бы один подход»; only «Изменить» leads on.

**Evidence**: `B-fresh-clean/artifacts/J2-picker-empty.png`, `EMPTY-light-E4.png`, `EMPTY-dark-E4.png`, `E12-detail.png`, `E12-addtoplan.png`, `E12-record-empty-saved.png`;
`B-fresh-catalog/artifacts/j3-01-empty-detail.png`, `j3-01-empty-in-plan.png`.

**Root cause**: observed UI behaviour (`data-testid="workout-detail-start"` disabled without a hint). Content side: FD-01 / FD-07. Not pinned to a line by the Judge.

**Likely layer**: UX dead-end (with missing system content).

**Scope**: empty and no-result picker states show an explicit «Создать упражнение» CTA. The zero-exercise detail explains why «Начать» is unavailable and offers
«Добавить упражнение». Validate «Добавить в план» / «Записать» before submit.

**Acceptance (journey re-audit from S0)**: **B-fresh-clean J2 + E4 + E12** on a clean install: a new user builds a workout and adds the first exercise **without having to guess to
type**. From a 0-exercise detail one tap leads to adding an exercise. Then Начать → Live → finish → Журнал, and a reload keeps everything.

**Dependencies**: independent. Severity drops to P2 once FD-01/FD-07 ship a non-empty library.

---

## [FUNC-AUDIT P1] Expired subscription does not gate course start on the v2 path (FD-05)

**Spec rule**: `docs/plan-and-specs.md:339-341` (§14 default, in force per §16:364). After the trial, courses in the plan are paused and «Начать» → subscription
screen. Free workouts, history and analytics stay free. Also §10.3:212. **Owner to confirm (decision D6).**

**Repro from S0**: a user whose `subscription_expires_at` has passed (a real user reaches this by letting the trial end; the cache stays `trial`). C profile `audit_expired`
(tg 7300006) → Планы → «Начать» → «Начать» → «Готов» → 10 → «Готово» ×2 → «Завершить» → «3» → «Сохранить и завершить».

**Expected**: «Начать» on a course row leads to the subscription screen with an actionable way to pay. A free/custom workout still starts.
**Actual**: banner «Нет активной подписки. Оформи её в боте, потом возвращайся сюда.», but «Начать» is enabled. The course session starts, completes and is saved
(«1 из 3», Журнал after reload).

**Evidence**: `C-existing/artifacts/J6_audit_expired.trace.txt` (06:49:41, 06:49:54), `J6_audit_expired__02_plans_expired.png`, `J6_audit_expired__03_after_expired_train.png`;
`B-fresh-clean/artifacts/J6-expired-*.png`, `trace-J6.log`.

**Root cause (confirmed)**
- `app/web/routes_v2.py:1584-1608` `start_live_session` → `LiveSessionService.start_session`: no `SubscriptionService.has_access`.
- The only gates are legacy: `app/web/routes.py:736-737`, `:1710-1711`.
- The banner is the legacy readiness status text (`webapp-frontend/src/DashboardScreen.tsx:707-713`) and does not disable the button.
- `has_access` has no admin bypass (`app/services/subscription.py:104-106`).
- Existing tests cover only the legacy endpoints (`tests/test_web/test_workout.py:150`, `test_backdate.py:112`). No e2e seed creates an expired user.

**Likely layer**: subscription/auth defect.

**Scope**: gate program-backed live starts (and, if confirmed, new course inclusions) with `has_access`. UI: «Начать» on a course → subscription screen. Keep
free workouts open. Add a v2 backend test and an e2e expired seed.

**Acceptance (journey re-audit from S0)**: **C J6** audit_expired and audit_expired_b: Планы → «Начать» on the course → subscription screen (reload keeps the state). An own/free workout
still starts and completes. After the admin grant (bot `admin_grant_days`), the course starts and completes. Журнал and the plan counters are unchanged by gating.

**Dependencies**: owner decision D6. Pairs with the P2 item FD-11 (stale status label, no pay action). Independent of FD-01..FD-04.

---

## P2 backlog (single section; no individual issues)

| FD | Title | Layer | Key pointer |
|---|---|---|---|
| FD-06 | Catalogue scripts not run by deploy; `seed_exercise_library.py` crashes standalone; `seed_collections.py` likely the same; stale docs on `scripts/` in the image | seed/test illusion | `scripts/seed_exercise_library.py:15-16`, `deploy/deploy-run.sh:32-38`, `Dockerfile:11`. Fold into the P0 draft |
| FD-07 | Thin catalogue after the scripts: 1 program, no pull-up library exercise, internal «Факультатив — …» in the picker, empty collection | missing system content | owner decisions D1–D3; `9e3f1a4b6c80_collections.py:18-23` |
| FD-08 | Future course weeks look empty; copy week «Скопировано: 0»; › creates empty weeks (spec'd; explain or preview in the UI) | UX / valid domain difference | `docs/PROJECT_SPEC.md:677-680,684-685`; `app/services/plan_week.py:121-150` |
| FD-09 | Strength block: 4 sets promised, Live runs 1 (bot-era users migrate from 4 to 1) | legacy/v2 convergence (progression decision; plan first per CLAUDE.md) | `app/services/live_session.py:441` |
| FD-10 | Pre-screen target ≠ Live target for gap users (9 vs 11) | legacy/v2 convergence | `SessionPreScreen.tsx:114` vs `progression_state` |
| FD-11 | Stale «пробный период (осталось 0 дн.)» in Профиль; no pay action in the Mini App | subscription/auth | `app/services/subscription.py:89-102`; `app/web/routes.py:488` |
| FD-12 | Removing a manual plan row rewrites the Журнал title to «Тренировка» | persistence | `app/db/repositories/training_plans.py:250-262`; `models_program.py:455` CASCADE; `routes_v2.py:1104` |
| FD-13 | Legacy delete/edit not reflected in Аналитика (backfilled copy counted) | legacy/v2 convergence | `app/services/training_analytics.py:72` (no `exclude_backfilled`) |
| FD-14 | Native plan session in Журнал: no edit/clone/delete and no explanation | UX dead-end | `app/services/session_deletion.py::_verdict` REASON_PROGRAM |
| FD-15 | Activity «Повторить» loses type/duration («Тренировка», «Без категории») | API/backend | `routes_v2.py:1367` → `SessionEditingService.clone` |
| FD-16 | Summary/detail lose block names («— 3/3», «Упражнение») | API/frontend | `routes_v2.py:286` `_catalog_exercise_names` |
| FD-17 | Onboarding baseline not used for the course start target (8 → 3×10) | product decision | `app/services/program_inclusion.py` `initial_target_*` |
| FD-18 | «Начать» on a too-early day → text dead end, no earliest date | UX dead-end (valid rule) | C `J6_audit_trial.trace.txt` |

P3 polish (FD-19..FD-26) is listed in `docs/FUNCTIONAL_AUDIT_WAVE_1.md` §6.
