# PROFILES — B-fresh-catalog (DB `pullup_audit_d`, :8092, Redis db 2, tg ids 7200001+)

## Step 0 — SYSTEM CONTENT (script-created, NOT by migrations)

Install = `alembic upgrade head` (already done) + the two repository catalogue scripts, run the way an operator would
(`BOT_TOKEN=audit-token DATABASE_URL=...pullup_audit_d PYTHONPATH=. .venv/bin/python scripts/<x>.py`). Nothing else was created.
Pre-state: `SELECT count(*) FROM programs` = 0.

| # | Command | Result |
|---|---|---|
| 1 | `scripts/backfill_multi_program.py --dry-run` | OK. "Онбордившихся пользователей: 0 … будет мигрировано: 0". Dry-run does NOT call `seed_catalog` (`seed = None if dry_run`). |
| 2 | `scripts/backfill_multi_program.py` | OK. Users 0 → TrainingPlan 0. `seed_catalog` ran (see below). |
| 3 | `scripts/seed_exercise_library.py` (as documented) | **FAILED** — `sqlalchemy.exc.NoReferencedTableError: Foreign key associated with column 'exercises.owner_user_id' could not find table 'users'` (script imports only `models_program`, `users` table not in metadata). Full traceback: `artifacts/seed_exercise_library_standalone_error.txt`. See F-B-fresh-catalog-10. |
| 3b | `scripts/audit/b_fresh_catalog_seed_library.py` (audit wrapper: `import app.db.models` first, then calls `seed_exercise_library.main()` unchanged) | OK: «Exercise Library засидирована: Планка id=7, Отжимания id=8». TEST HARNESS WORKAROUND for the script bug; the script itself is unmodified. |

Content now present (SELECT, `pullup_audit_d`):

| Table | Rows | Created by |
|---|---|---|
| programs | 1: id1 «Подтягивания» (structure_type=recurring, category=pull_ups, goal «Рост числа подтягиваний: объём (блок A) + сила (блок Б)», `reference_assessment_protocol_id` NULL) | backfill `seed_catalog` — SYSTEM CONTENT |
| program_items | 2: (prog1, base, exercise 1, ×3/нед), (prog1, base, exercise 2, ×3/нед); `day_of_week` NULL | backfill — SYSTEM CONTENT |
| exercises | 8, all `source_type=system`: 1 «Подтягивания — объём» (block_a), 2 «Подтягивания — сила» (block_b), 3 «Факультатив — подтягивания на максимум», 4 «Факультатив — подтягивания W», 5 «Факультатив — 3 минуты подтягиваний», 6 «Факультатив — подтягивания на объём» (ids 1–6 backfill), 7 «Планка» (time, «Общая физическая подготовка»), 8 «Отжимания» (reps, same) (ids 7–8 seed_exercise_library via wrapper) | SYSTEM CONTENT |
| complexes / complex_items | **0 / 0** (no system workouts/complexes) | — |
| assessment_protocols | 3: «Максимум подтягиваний» (reps), «Вис на перекладине, сек» (time), «Подтягивания с весом, кг» (weight). created_at 05:58:10 = migration time, i.e. created by MIGRATIONS, not the scripts | migrations |
| collections | 1: slug `start-with-pull-ups`, «Начни с подтягиваний», is_published=true, **0 collection_items** (created by migration, created_at at migration time) | migrations |

Net: the catalogue = **one program** (Подтягивания), 2 general exercises (Планка, Отжимания), no system workouts, an empty published collection.

## Profile `audit_fresh_active`

Each journey used a NEW telegram id so it started at S0 (onboarded, trial active, nothing else). Onboarding was done THROUGH THE UI
(works: baseline → «Уровень зафиксирован» → 5-step questionnaire → «Готово»); no `e2e_seed._onboard` injection was needed.

| tg id | Journeys | Created entities |
|---|---|---|
| 7200001 | J1, J4, J8 | users row, baseline (8 reps), questionnaire, trial subscription — AUTH NECESSITY / DOMAIN NECESSITY (via UI onboarding). Then via UI only: training plan + program inclusion («Добавить в план»), live sessions, plan items (Планка), week creation. |
| 7200002 | J2, J3 | same onboarding; via UI: workouts «Моя тренировка спины», «Пустая», user exercise «Австралийские подтягивания», plan items, sessions |
| 7200003 | E-matrix, search | same onboarding; one UI add-to-plan (exercise Планка) to reproduce F-01 |
| 7200004 | dark pass | onboarding only (dark pass INVALID, see EMPTY_STATES.md) |
| 7200011–7200014 | Playwright specs | same onboarding; per-spec UI actions |

Entity classification:
- AUTH NECESSITY: `users` row (created by first `/api/hello` w/ valid initData), trial subscription.
- DOMAIN NECESSITY: baseline, questionnaire answers (weight 78, height 180, male, 1995-05-15, Europe/Moscow), coin/achievement grants given automatically (Профиль shows «50 Монет», «1 Ачивка» at 0 trainings).
- SYSTEM CONTENT: program/exercises listed above.
- TEST CONVENIENCE: none. No SQL writes, no `e2e_seed`, no injected plans/sessions/history. All DB reads were read-only diagnostics after observed failures.
- TEST HARNESS INJECTION: none (only the seed-script wrapper in step 3b, which is environment setup, not user state).
