# System content contract

Status: **IMPLEMENTED** (issue #296; Functional Differential Audit Wave 1 findings FD-01 P0, FD-06, FD-07 — see
`docs/FUNCTIONAL_AUDIT_WAVE_1.md`). Owner decisions D1–D5 are final and recorded below. This document is the
contract for what a fresh install ships, how it ships, and how it is identified.

## 1. Why this contract exists

Before #296, `deploy/deploy-run.sh` ran `docker compose build app web` → `alembic upgrade head` →
`docker compose up -d app web`, and migrations shipped only 3 assessment protocols and an empty collection. A clean
install had programs=0, exercises=0, complexes=0: a new user saw «Каталог курсов появится здесь позже.» and the
primary path (course → plan → Начать) could not start. Content existed only if an operator ran repository scripts by
hand, and one of them (`seed_exercise_library.py`) crashed standalone. The e2e seeds created programs/exercises
themselves, so the test suite never noticed.

## 2. Mechanism (D4): idempotent, deterministic Alembic data migration

Revision **`a4c8e1f7b2d9`** (`app/db/migrations/versions/a4c8e1f7b2d9_system_content_seed.py`,
`down_revision = 9e3f1a4b6c80`). Pattern of `f6a7b8c9d0e1` (protocols).

- **Additive data only**; schema unchanged; compatible with the previous code.
- **Find-or-create by a stable natural key** (nothing is updated if found), so environments where
  `backfill_multi_program.py` / `seed_exercise_library.py` already created rows get **no duplicates**; running the
  migration twice, `downgrade -1` + `upgrade`, or calling `seed_system_content()` twice is a no-op.
- **Frozen snapshot, not live constants:** the program config JSON, names, roles and subcategories are literals copied
  into the migration (value snapshot of `app/domain/constants.py` as of 2026-10-05). A later change of the constants
  must not retroactively change what this revision writes.
- **No user-specific rows, ever:** no `TrainingPlan`, `ProgramInclusion`, `PlanWeek`/`PlanItem`, session, subscription
  or history. `backfill_multi_program.py::backfill_all` (which also enrols every onboarded user) is NOT reused;
  only the catalogue part of it (`seed_catalog`) has the same shape.
- **`downgrade` is an intentional no-op:** by downgrade time, plans, course inclusions, frozen session snapshots and
  user history may reference these rows (`Complex`/`ComplexItem`/`Exercise`/`PlanItem` are never deleted by session
  operations; constitution V — do not delete history). Rolling the revision back must not destroy data.
- Production does not depend on manual scripts. `scripts/seed_exercise_library.py`, `seed_collections.py` and
  `backfill_multi_program.py` remain operator tools (the first now runs standalone, see §6).

## 3. What ships (exact list)

| Content | Natural key | Notes |
|---|---|---|
| Strategy profile «Пошаговая прогрессия подтягиваний» (STEP, config `{}`) | `name` | same as `seed_catalog` |
| Program **«Подтягивания»** (category `pull_ups`, RECURRING, STEP profile, frozen config) | `programs.name` | goal «Рост числа подтягиваний: объём (блок A) + сила (блок Б)»; config = block_a(10/3/20/10), block_b(3/4/7/3), step_pct 0.05, weak_streak 3, set_length 12, min_rest_days 2 |
| Role exercises «Подтягивания — объём» (`block_a`), «Подтягивания — сила» (`block_b`) + 2 ProgramItems (BASE, ×3/нед, free pool) | exercise `(name, owner IS NULL)`; item `(program_id, exercise_id)` | internal |
| Elective exercises «Факультатив — подтягивания на максимум / W / 3 минуты подтягиваний / на объём» (`elective_max_reps_ladder` / `_w_ladder` / `_three_minutes` / `_volume_target`) | `(name, owner IS NULL)` | internal; history uses them |
| **Public library (D1)** — `owner_user_id IS NULL`, `source_type='system'`, no subcategory: «Подтягивания», «Подтягивания с резиной», «Подтягивания с отягощением», «Австралийские подтягивания», «Лопаточные подтягивания» (reps, category «Подтягивания»); «Вис на турнике» (time, «Хват»); «Планка» (time) and «Отжимания» (reps) (category «Общая физическая подготовка») | `(name, owner IS NULL)` | no duplicates of equivalents |
| **System workouts (D2)** — `Complex(source_type='system', owner NULL)` + 1 `ComplexItem` (exercise «Подтягивания», `sets=0` placeholder as in the Builder, `protocol` = definition JSON) | `(name, source_type='system', owner IS NULL)` | see §4 |
| Collection item: program «Подтягивания» in `start-with-pull-ups` («Начни с подтягиваний») | `(collection_id, program_id)` | the collection row itself comes from `9e3f1a4b6c80`; the collection is now non-empty, so Home shows it |
| Assessment protocols (3) | — | unchanged, `f6a7b8c9d0e1` |

D5: no second course.

## 4. System workouts and the protocols chosen (D2)

They are real workouts (open detail → «Начать» builds a frozen snapshot → live session; «Добавить в план»), not fake
exercise records. The formats are those of the former «Факультатив» types, expressed with the existing protocol v1
(`docs/adr/WORKOUT_PROTOCOL_V1.md`):

| Workout | Protocol | Why |
|---|---|---|
| «Максимум подтягиваний» | `max_effort`, 4 attempts, rest 120 s | the elective was a 4-set max ladder with rest 180/120/60; the protocol carries one rest value, so the middle one |
| «W-лесенка» | `reps_sets` static, 17 sets × 3 reps, rest 10 s | the W ladder is 5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5 (17 sets, rest 10 s). `reps_sets` takes one reps value per set, so the target is the average (53/17 ≈ 3); the exact ladder is a known limitation (needs a per-set reps protocol — not invented here) |
| «3 минуты подтягиваний» | `interval` 180 s, 10 s work / 20 s rest, starts with work | exactly the ADR interval example |
| «Объём ×5» | `reps_sets` static, 5 sets × 8 reps, rest 120 s | «на объём» = 5 sets of 6–10 reps (the midpoint) |

## 5. Visibility rules

- **Public exercise library** (`GET /api/v2/exercises`, picker, search, collections) = system exercises (any
  `owner`-less, `source_type='system'`) plus the user's own, **excluding internal ones** — `subcategory` in
  `block_a`/`block_b` (STEP roles) or starting with `elective_` (D3). One definition:
  `app/domain/multi_program.py::is_internal_exercise_subcategory` and its SQL mirror
  `app/db/repositories/programs.py::public_exercise_filter`. The boundary is by `subcategory`, not by name (a user's
  own exercise called «Факультатив …» is not hidden). Internal exercises stay in the DB and in history; the public
  `POST /plan-items` rejects them (404).
- **Workout catalogue** (`GET /api/v2/workouts/catalog`): `source_type='system' AND owner_user_id IS NULL AND
  archived_at IS NULL`, read-only, visible to every user. «Мои тренировки» (`GET /api/v2/workouts`) stays own-only.
  A system workout can be opened, started, added to a plan and favorited; it cannot be edited or deleted (404).
- Home shows the programs catalogue (including «Подтягивания»), the «Подборки» row (non-empty) and a «Готовые
  тренировки» section; search covers programs, own and ready-made workouts, exercises and tests.

## 6. Scripts and e2e

- `python scripts/seed_exercise_library.py` runs in a clean interpreter (it now registers the `users` table; it used to
  fail with `NoReferencedTableError exercises.owner_user_id → users` on INSERT). Same natural key as the migration, so
  on a migrated DB it creates nothing. `seed_collections.py` has no such bug (verified).
- e2e: `scripts/e2e_seed.py` no longer creates a second global «Подтягивания» program; seeds that need it call
  `seed_catalog`, which finds the shipped rows. The claim «the catalogue comes from migrations» is true exactly for the
  shipped content in §3; other e2e programs («Свип: курс», «Дискавери: …») are still created by their seeds.
- The fresh-install journey (`webapp-frontend/e2e/scenarios/fix-wave1/fresh-install-content.spec.ts`) runs against a
  DB with migrations only (no seeds, new UI-onboarded user).

## 7. Tests

- `tests/test_scripts/test_system_content_migration.py` — deploy-level: scratch DB, `alembic upgrade head` as a
  subprocess; asserts program, library, workouts, collection item, zero user rows; double upgrade, `downgrade -1` +
  `upgrade`, double `seed_system_content()`; a DB where `seed_catalog` / `seed_exercise_library` (/ `seed_collections`)
  ran before the migration gets no duplicates.
- `tests/test_scripts/test_content_scripts_standalone.py` — content scripts in a clean interpreter, exit 0, idempotent
  (on an empty library, where the INSERT path that used to crash actually runs).
- `tests/test_web/test_v2_system_content.py` — public library excludes internal exercises, catalogue endpoint, every
  system workout opens and starts, add to plan, not editable, favorites.
- conftest truncates `complexes` too (the migration ships system `Complex` rows that would otherwise survive).

## 8. Read-only staging verification (owner runs; no writes)

From `/root/pullup-trainer-bot-staging` (adjust the service name if it differs). After the deploy that includes
`a4c8e1f7b2d9` all of the following must be ≥ the numbers in §3:
```sql
-- docker compose exec db psql -U <user> -d <db> -c "<query>"
SELECT 'programs' k, count(*) FROM programs
UNION ALL SELECT 'programs_pull_ups', count(*) FROM programs WHERE category = 'pull_ups'
UNION ALL SELECT 'program_items', count(*) FROM program_items
UNION ALL SELECT 'exercises_public_library', count(*) FROM exercises WHERE owner_user_id IS NULL AND subcategory IS NULL
UNION ALL SELECT 'exercises_internal_roles', count(*) FROM exercises WHERE owner_user_id IS NULL AND (subcategory IN ('block_a','block_b') OR subcategory LIKE 'elective\_%')
UNION ALL SELECT 'complexes_system', count(*) FROM complexes WHERE owner_user_id IS NULL AND source_type = 'system'
UNION ALL SELECT 'collection_items', count(*) FROM collection_items
UNION ALL SELECT 'duplicate_system_exercise_names', count(*) FROM (SELECT name FROM exercises WHERE owner_user_id IS NULL GROUP BY name HAVING count(*) > 1) d
UNION ALL SELECT 'duplicate_program_names', count(*) FROM (SELECT name FROM programs GROUP BY name HAVING count(*) > 1) d;
```
`duplicate_*` must be 0 on an environment that never ran the scripts twice; on an environment where an operator ran
them (or e2e seeds ran), duplicates that predate this migration are not touched by it (find-or-create never deletes).
Per constitution VII, verify on the real environment after the deploy: `GET /api/v2/programs`,
`GET /api/v2/exercises`, `GET /api/v2/workouts/catalog` each non-empty for a fresh user.
