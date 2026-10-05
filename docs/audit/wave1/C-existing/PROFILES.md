# PROFILES — C-existing (DB `pullup_audit_c`, port 8093, Redis db 3, tg 7300001+)

Creation path (production-like, in this order):
1. `alembic upgrade head` (pre-migrated DB provided by harness).
2. **Legacy (Telegram-bot-era) users** created with the same services the bot used: `UserRepository.create` -> `OnboardingService.record_baseline_and_start` -> `OnboardingService.complete_questionnaire_and_start_trial` -> `EquipmentItemRepository.create` (резина 15 кг) -> `WorkoutRepository.record_workout` x N (legacy `workouts/blocks/baselines`). Recipe = `scripts/e2e_seed.py::seed_ready` / `seed_journal_dedupe` (read as harness), driven by `scripts/audit/c_seed_profiles.py`. Timestamps are back-dated through the `now`/`performed_at` arguments (the normal API of those services), so trials expire naturally.
3. **Real operator conversion**: `python scripts/backfill_multi_program.py` (also seeds the catalogue: Program «Подтягивания», 2 role Exercises, 4 elective Exercises, ProgressionStrategyProfile, ProgramItems) — run for real, unmodified. 
4. `scripts/seed_exercise_library.py` (Планка, Отжимания). NOTE: run as documented (`python scripts/seed_exercise_library.py`) it crashes (`NoReferencedTableError exercises.owner_user_id -> users`, models module not imported); it only worked after pre-importing `app.db.models` (see F-C-17). 
5. One TEST HARNESS INJECTION (see bottom). 
6. Snapshot `scripts/audit/c_seed_snapshot.sql` = state S0; `scripts/audit/c_reset.sh` restores it, `scripts/audit/c_run_all.sh` replays the whole audit.

Legend: AUTH = AUTH NECESSITY, DOMAIN = DOMAIN NECESSITY, SYS = SYSTEM CONTENT, CONV = TEST CONVENIENCE (allowed here: these are existing-user profiles, not fresh-user journeys).

| tg | profile | legacy history (days ago) | subscription at S0 | backfill result |
|---|---|---|---|---|
| 7300001 | audit_existing_active | 6 workouts (25,21,17,13,9,5), band 15 kg, onboarded 30 d ago | ACTIVE (Stars ref audit-c-stars-1, 60 d from 14 d ago -> 2026-11-20) | plan + inclusion «Подтягивания» + current PlanWeek (wk 1, 5–11 окт) |
| 7300002 | audit_legacy_existing | 3 workouts (10,6,3) + 1 legacy ElectiveWorkout (8 d, ladder 12/10/8/6); never opened Mini App | TRIAL (onboarded 12 d ago, ends 2026-10-07) | idem; elective -> TrainingSession(source=elective) |
| 7300003 | audit_returning_week_transition | 6 workouts (30..12) | ACTIVE (Stars, until 2026-12-10) | backfill run with now=-10 d (PlanWeek -1, 21 сен), current week removed by injection |
| 7300004 | audit_trial | 2 workouts (4,1) | TRIAL (10 d left) | idem |
| 7300005 | audit_active_paid | 5 workouts (45,38,30,20,8) | ACTIVE (Stars 60 d from 20 d ago) | idem |
| 7300006 | audit_expired | 3 workouts (36,30,24) | trial ended 2026-09-09; cache still `trial` (exactly what nothing-flips-status leaves in prod) | idem |
| 7300007 | audit_trial_rested (added: audit_trial trained yesterday -> MIN_REST_DAYS) | 2 workouts (7,4) | TRIAL | idem (incremental real backfill run) |
| 7300008 | audit_expired_b (second expired profile for grant -> train) | 2 workouts (40,33) | trial ended ~2026-09-04 | idem |
| 7300009 | audit_persist (J7) | 3 workouts (20,10,5) | ACTIVE | idem |
| 7300010 | audit_interrupt (J8) | 3 workouts (20,10,5) | ACTIVE | idem |
| 7300099 | admin actor | none (exists only as the admin id inside `scripts/audit/c_admin_grant.py`, `settings.admin_ids` patched in that process only; not a DB user) | – | – |

## Entities
| entity | class | how created |
|---|---|---|
| `users` rows (telegram_id, username, onboarding_completed_at, weight/height/gender/birth_date/timezone Europe/Moscow) | AUTH + DOMAIN (the Mini App auth requires a user; questionnaire fields are required by `complete_questionnaire_and_start_trial`) | OnboardingService |
| baselines (10 reps), workout_sets | DOMAIN | OnboardingService.record_baseline_and_start |
| `equipment_items` «Резина 15кг» | DOMAIN (band equipment is what the bot-era onboarding produced for 10 reps) | EquipmentItemRepository |
| legacy `workouts`/`blocks` (A 10,10,10 max 11–13; B 3,3,3,3) | DOMAIN (history of a bot-era user) | WorkoutRepository.record_workout |
| legacy `elective_workouts` (7300002) | DOMAIN | session.add |
| `subscriptions`/users.subscription_* | AUTH/DOMAIN (trial from onboarding; ACTIVE via `SubscriptionService.extend(source=STARS)`) | services |
| Program «Подтягивания», role Exercises, elective Exercises, strategy profile, ProgramItems | SYSTEM CONTENT | `backfill_multi_program.seed_catalog` (real script) |
| Exercises Планка / Отжимания | SYSTEM CONTENT | seed_exercise_library |
| TrainingPlan, ProgramInclusion(snapshot, progression_state), PlanItems, PlanWeek, TrainingSession/SessionBlock/SetLog copies of history | DOMAIN (backfill output) | real backfill |
| Everything created later (live sessions, journal entries, activities) | produced through the UI by the specs | – |
| `scripts/audit/c_seed_snapshot.sql`, c_reset.sh, c_run_all.sh | TEST CONVENIENCE (replay only) | |

## TEST HARNESS INJECTIONS (never count as PASS of the upstream path)
1. **Time travel (audit_returning_week_transition)** — `backfill_all(session, now=<today-10d>)` was called from `c_seed_profiles.py pre` so the plan/PlanWeek (-1, start 2026-09-21) were created "in a previous week". The later real operator re-run of the script (needed for the other profiles) materialised the current week for this user as well (script's "already migrated" branch calls `ensure_current_plan_week`), so `scripts/audit/c_inject_week_transition.sql` removes only that current-week row:
```
DELETE FROM plan_items WHERE plan_week_id IN (SELECT id FROM plan_weeks WHERE training_plan_id=1 AND start_date='2026-10-05');
DELETE FROM plan_weeks WHERE training_plan_id=1 AND start_date='2026-10-05';
```
   (re-applied after each incremental backfill run). Upstream path "user opens app after a week boundary and the week is created" is exercised by the app, but the S0 itself is injected.
2. **Clock-shifted history**: all legacy rows are created with back-dated `performed_at`/`now` arguments (service API, no SQL).
3. **Admin grant** is NOT an injection: executed through the real bot handler (`admin_grant_days` callback + numeric message) via `aiogram Dispatcher.feed_update` with a StubSession bot (`scripts/audit/c_admin_grant.py`, same technique as `tests/test_bot/conftest.py`); admin id = 7300099 patched into `settings.admin_ids` inside that process only.
4. Playwright mock of `window.Telegram.WebApp` (platform difference): the console error "Telegram SDK init() failed ... launch parameters" appears on every page load and is a mock artefact, not an app defect. Native `confirm()` dialogs are auto-accepted by the specs and logged as `DIALOG`.
