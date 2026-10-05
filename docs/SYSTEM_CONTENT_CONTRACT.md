# System content contract (draft, Functional Differential Audit Wave 1, #295)

Status: **PROPOSAL**. Nothing here is implemented. The proposal comes from Wave 1 finding FD-01 (P0), with FD-06 and FD-07 (see
`docs/FUNCTIONAL_AUDIT_WAVE_1.md`). It defines the minimum system content that a fresh install and a fresh user need,
where each piece comes from today, and the delivery options that the owner must choose between.

## 1. Why this contract exists

The deploy procedure (`deploy/deploy-run.sh:32-38`) runs exactly three steps: `docker compose build app web`, then
`docker compose run --rm app alembic upgrade head`, then `docker compose up -d app web`. Migrations ship 3 assessment protocols
and 1 collection with 0 items. They ship **no programs, no exercises and no system workouts**. Verified on
`pullup_audit_b` (alembic head `9e3f1a4b6c80`): programs=0, exercises=0, complexes=0, program_items=0,
assessment_protocols=3, collections=1 with 0 collection_items, so the collection is hidden
(`app/db/repositories/collections.py:87`).

A fresh user on such an install sees «Каталог курсов появится здесь позже.» (`webapp-frontend/src/HomeScreen.tsx:420-422`), and
the product's primary path (course → plan → Начать) cannot start. Catalogue content exists only if an operator ran
repository scripts by hand. The test suite never noticed, because the e2e seeds create programs and library exercises
themselves (see the false-confidence audit in the main report).

## 2. Content inventory

Legend: **clean** = `alembic upgrade head` only (B-fresh-clean). **catalogue** = clean plus `backfill_multi_program.py` plus
`seed_exercise_library.py` (B-fresh-catalog). Each image column records whether the content is in the image: the `app`
(bot) image copies `scripts/` (`Dockerfile:11`, commit `1685a76`), and the `web` image (`Dockerfile.web`) copies only `app/`.
Staging is unreachable from the audit, so every staging cell is **UNKNOWN**; the SQL in §4 settles it.

| # | Content | EXPECTED IN CLEAN INSTALL? | SOURCE OF CREATION today | MIGRATION? | SEED SCRIPT? | ADMIN-ONLY? (UI to create) | IN DEPLOY IMAGE? | MISSING LOCALLY (clean)? | ON STAGING |
|---|---|---|---|---|---|---|---|---|---|
| C1 | Program «Подтягивания» (category `pull_ups`, RECURRING, STEP) + 2 ProgramItems (block A ×3, block B ×3/нед) + ProgressionStrategyProfile STEP | **YES**. This is the product's core value; Home/Планы CTAs assume it (PROJECT_SPEC.md:695-696 «переход на «Главную» с каталогом программ») | `scripts/backfill_multi_program.py::seed_catalog` (`:245-290`). It runs only in a non-dry run, and it also **migrates/enrols every onboarded user without a TrainingPlan** (module docstring §2) | NO | YES (side-effecting backfill, not a pure seed) | NO admin UI or bot command creates programs (no `Program(` outside scripts/tests) | script in `app` image only; not run by deploy | **YES (missing)** | UNKNOWN. Indirect evidence that backfill ran on the owner's environment: #279 / #282 / #284 fixed backfilled elective sessions and backfill duplicates that the owner saw («баг только на develop/staging», `docs/ENGINEERING_NOTES.md:2576-2581`) |
| C2 | Role exercises «Подтягивания — объём» (`block_a`), «Подтягивания — сила» (`block_b`) | YES (internal, required by C1) | same `seed_catalog` | NO | YES | NO | as C1 | YES | UNKNOWN (as C1) |
| C3 | Elective exercises «Факультатив — подтягивания на максимум / W / 3 минуты подтягиваний / на объём» (`elective_*`) | YES for migrated history and electives, but **internal**. Today they leak into the public picker/search (FD-07) | same `seed_catalog` | NO | YES | NO | as C1 | YES | UNKNOWN |
| C4 | Public exercise library: «Планка» (time), «Отжимания» (reps), category «Общая физическая подготовка» | YES (picker must not be empty) | `scripts/seed_exercise_library.py` | NO | YES, but it **crashes as documented** (`NoReferencedTableError exercises.owner_user_id → users`; `:15-16` imports only `models_program`). Works only when `app.db.models` is imported first (FD-06) | NO | in `app` image, not run | YES | UNKNOWN |
| C5 | **Pull-up library exercises** (e.g. «Подтягивания», «Австралийские подтягивания», negatives, hangs) | **YES (owner decision on the list)**. A fresh custom pull-up workout needs at least one pull-up exercise (B-catalog F-11: search «подтягивания» returns only «Факультатив …») | **nothing**: no script, no migration | NO | NO | NO | — | YES | UNKNOWN (probably absent: no source exists) |
| C6 | System workouts / complexes (`complexes.source_type='system'`) | **OWNER DECISION**. The reference ships catalogue workouts (GOLDEN_TRACES R-J1 R2/R4: category rows "N Workouts", Workout Detail with Start) | nothing | NO | NO | NO | — | YES (0) | UNKNOWN |
| C7 | Assessment protocols «Максимум подтягиваний» (reps), «Вис на перекладине, сек» (time), «Подтягивания с весом, кг» (weight) | YES | migration `f6a7b8c9d0e1_assessment_protocols_seed.py` (idempotent `WHERE NOT EXISTS`) | **YES** | — | NO | yes (migrations in `app/`) | **NO (present)** | expected present if staging is at head; verify |
| C8 | Collection «Начни с подтягиваний» (`start-with-pull-ups`) + items = programs with category `pull_ups` | YES when C1 exists | migration `9e3f1a4b6c80_collections.py` creates the row; it fills items **only if programs already exist at migration time** (`:18-23`, `:64-71`); otherwise `scripts/seed_collections.py` | partly | YES (`seed_collections.py`, not run by any explorer; it imports only `models_program` and repositories, so the same crash class as C4 is INFERRED but untested) | NO | in `app` image, not run | row present, **0 items → hidden** | UNKNOWN |
| C9 | Collection items for a fresh install where C1 arrives after the migration | YES | `seed_collections.py` only | NO | YES | NO | not run | YES | UNKNOWN |

Not system content (created per user, correctly): TrainingPlan, PlanWeek, PlanItem, user Workouts/Exercises, sessions,
subscriptions, baseline.

## 3. Minimum content for "a fresh user can complete a first workout on every path"

1. **Program path:** ≥1 published program with ≥1 ProgramItem that materialises into the current week (C1, C2).
2. **Custom path:** a non-empty public library with ≥1 pull-up exercise (C4 plus C5), and internal role/elective exercises
   hidden from the picker (C3 visibility rule).
3. **Discovery:** collection C8/C9 non-empty, or no collection row at all. A published but empty row is noise.
4. **Assessment:** C7 (already satisfied).
5. Optional, by owner decision: system workouts C6, so that a free workout can start from the catalogue without the builder
   (the reference's catalogue-first model).

## 4. Read-only staging verification (owner runs; no writes)

From `/root/pullup-trainer-bot-staging` (staging compose project; adjust the service name if it differs):
```sql
-- docker compose exec db psql -U <user> -d <db> -c "<query>"
SELECT 'programs' k, count(*) FROM programs
UNION ALL SELECT 'programs_pull_ups', count(*) FROM programs WHERE category = 'pull_ups'
UNION ALL SELECT 'program_items', count(*) FROM program_items
UNION ALL SELECT 'exercises_system', count(*) FROM exercises WHERE owner_user_id IS NULL
UNION ALL SELECT 'exercises_public_library', count(*) FROM exercises WHERE owner_user_id IS NULL AND subcategory IS NULL
UNION ALL SELECT 'exercises_internal_roles', count(*) FROM exercises WHERE owner_user_id IS NULL AND (subcategory IN ('block_a','block_b') OR subcategory LIKE 'elective_%')
UNION ALL SELECT 'complexes_system', count(*) FROM complexes WHERE owner_user_id IS NULL
UNION ALL SELECT 'assessment_protocols', count(*) FROM assessment_protocols
UNION ALL SELECT 'collections_published', count(*) FROM collections WHERE is_published
UNION ALL SELECT 'collection_items', count(*) FROM collection_items
UNION ALL SELECT 'orphan_manual_plan_items (FD-02)', count(*) FROM plan_items WHERE plan_week_id IS NULL AND program_inclusion_id IS NULL
UNION ALL SELECT 'users_cache_active_but_expired (FD-05/FD-11)', count(*) FROM users
          WHERE subscription_status::text ILIKE ANY (ARRAY['trial','active']) AND subscription_expires_at < now();
SELECT name, category, structure_type, created_at FROM programs ORDER BY id;
SELECT id, name, subcategory, source_type FROM exercises WHERE owner_user_id IS NULL ORDER BY id;
```
Interpretation: programs=0 means FD-01 is live on staging (the owner's "no plan" and "cannot start" symptoms follow
directly). programs≥1 with exercises_public_library=0 means FD-07 / C5 is live (the "custom workout: no exercises"
symptom). Any orphan_manual_plan_items row means FD-02 is confirmed on staging.

## 5. Delivery mechanism options (propose; do not implement)

All options must respect `.claude/skills/migrations-safe/SKILL.md`: additive only, build → migrate → up order, data
scripts have a truly dry `--dry-run` and are idempotent. They must also respect constitution V (archive, do not delete)
and VII (verify on real data after deploy).

| Option | How | Pros | Cons / risks |
|---|---|---|---|
| **A. Data migration** (Alembic revision inserting C1–C5/C8 with `WHERE NOT EXISTS` by stable key) | Same pattern as `f6a7b8c9d0e1` (protocols) and `9e3f1a4b6c80` (collections) | Runs automatically in the existing deploy step; every install (prod, staging, CI, local, `pullup_test`) gets identical content; testable with a migrate-from-zero pytest | Content changes need new revisions. Program config/snapshot JSON lives in a migration and must stay frozen (a snapshot, not live constants; follow `_program_config_snapshot`). Must not duplicate rows that the earlier manual backfill created by name; needs a stable natural key (e.g. a new nullable `slug`, an additive column) or a name match. No enrolment of users. |
| **B. Idempotent startup seed** (app/web startup or a one-shot `seed` service in compose) | A pure `seed_system_content()` extracted from `seed_catalog` plus the library, called on boot | Content lives in Python next to the domain constants; easy to extend | Races between `app` and `web` booting together (needs an advisory lock); hidden write on every start; violates "explicit deploy steps" (constitution VII) unless it is a visible compose step; a failure mode at boot |
| **C. Run scripts from the image as an explicit deploy step** (`docker compose run --rm app python scripts/seed_system_content.py` after alembic in `deploy-run.sh`) | `scripts/` is already in the `app` image (`Dockerfile:11`) | Smallest change; explicit and visible; dry-run available | Needs a new **pure** seed script: `backfill_multi_program.py` must NOT be reused, because a re-run enrols every onboarded user without a plan into «Подтягивания» and migrates history. `seed_exercise_library.py` must first be fixed (import `app.db.models`). CI/e2e/local need the same step, otherwise the illusion persists. |

Judge's recommendation, for the owner to confirm: **A** for the immutable minimum (C1/C2/C3/C4/C5/C8 items), because it is the only
option that makes every environment, including `pullup_test`, equal by construction. Use **C** only for content that the owner
expects to edit often. In every option: add a deploy-level test that migrates an empty DB to head, starts the app with no seeds,
and asserts `GET /api/v2/programs` ≥1 and the public library ≥ the agreed list. Also remove the program and library creation
from `scripts/e2e_seed.py` (or assert that it is a no-op), so that e2e runs against the shipped content.

Data cleanup that accompanies the content fix (propose): orphan manual `plan_items` with `plan_week_id IS NULL` (FD-02). Per
constitution V, attach them to the plan's current week or archive them. Do not `DELETE` them. Count them first with the §4 query.

## 6. Owner decisions required

1. **D1** Which pull-up exercises ship in the public library (names, metric type, category label in Russian, not the
   `pull_ups` slug). Minimum proposal: «Подтягивания» (reps), «Австралийские подтягивания» (reps), «Негативные подтягивания»
   (reps), «Вис на перекладине» (time).
2. **D2** Whether system workouts (C6) ship, and which ones (the reference is catalogue-first).
3. **D3** Whether «Факультатив — …» exercises stay searchable for new users or become internal only (history keeps them).
4. **D4** Delivery mechanism A, B or C (§5).
5. **D5** Whether a second program ships at launch (PROJECT_SPEC/plan-and-specs §16 lists "Второй курс" as an owner input).
6. **D6** Confirm the subscription default in `docs/plan-and-specs.md` §14 (this governs FD-05; not catalogue, but it decides
   whether catalogue courses are paid content).
