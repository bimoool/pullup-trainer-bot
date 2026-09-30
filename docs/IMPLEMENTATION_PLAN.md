# IMPLEMENTATION_PLAN — статус и порядок работ

Продуктовое поведение — `docs/PROJECT_SPEC.md` (приоритетнее этого файла). Здесь — что сделано,
что дальше и как работать. Репозиторий — источник истины; каждый принятый чекпойнт сразу
коммитится **и пушится** (push ≠ merge, push ≠ deploy).

## Сделанные фазы (Workout Builder, issue #188 и связанные)

| Фаза | Что |
|---|---|
| A1 | Workout Protocol v1: `reps_sets`/`time_sets`/`max_effort`/`interval`, снимок Workout (ADR `docs/adr/WORKOUT_PROTOCOL_V1.md`) |
| B1/B2 | Interval-исполнение: серверный таймер, lazy-финализация, Live/Summary/Journal для interval |
| C1–C3 | Владение Exercise/Workout (`source_type`/`owner_user_id`), Workout core API, CRUD пунктов |
| C4a/C4b | «Мои тренировки» UI, Builder-форма пункта (все протоколы, отдых у max) |
| C5a/C5b | «Добавить Workout в план», фикс `POST /plan-items` для `complex_id` |
| D1–D4 | Управление PlanItem: перенос, удаление, UI |
| — | База реконструкции: `830f205` (`origin/feature/multi-program`) |

## REBUILD-1 — реконструкция принятого post-Phase-D состояния

Локальная работа после D4 была потеряна до пуша; восстановлено **поведение**, а не идентичные
коммиты. Ветка `rebuild/post-phase-d` (от `830f205`), каждый чекпойнт запушен сразу.

| Чекпойнт | Коммит | Содержание |
|---|---|---|
| R1 | `d51c8ae` (+ `879d94c` — чистка артефактов) | Смешанное исполнение: цели из prescription, замороженный снимок, `SessionBlock.started_at`, блок за блоком, ручной «Начать», серверный interval по блокам, адресация подходов блоком, сброс локального состояния, Summary по блокам |
| R2 | `297d4e9` | Journal v2: карточки, детали, безопасное удаление (`can_delete`, 404/409), пагинация |
| R3 | `ccac3e7` | Analytics v2: отдельный конвейер, активность 30 дней/12 недель, метрики по протоколам, UI «Тренировки \| Программа» |
| R4 | `0eb1272` | G2: валидация видимости в `POST /plan-items`; «Мои тренировки» с items без N+1 |
| R5 | см. `git log` ветки | Каноническая документация (`CLAUDE.md`, `docs/PROJECT_SPEC.md`, этот файл, `docs/ENGINEERING_NOTES.md`) |

Проверка: см. раздел «Отчёт о проверке» ниже.

## После REBUILD-1 (сделано, канонические ветки → `develop/current`)

| Что | Коммит |
|---|---|
| PRE-G3 стабилизация: порядок альбома, современные E2E-сиды, идемпотентные seed-ы, карантин устаревших specs | `cde9a6f`, `791daff` |
| Гонка `sets:batch` (reconnect + Complete) исправлена, `complete` идемпотентен | `9ac0dc7` |
| Референс Crimpd 8.5.3 (`android-ref-lab`, санитизированный `CRIMPD_PRODUCT_REFERENCE.md`), аудит архитектуры/тестов (#217, #218) | — |
| DOCS-3: `AGENT_EXECUTION_MODEL.md`, конституция v1.1 (безопасное удаление Builder-сессии), `CLAUDE.md` — короткая точка входа | `cfa2d41` |

Каноническая линия разработки — **`develop/current`** (не `feature/multi-program`).

## Phase G (develop/current)

| Что | Коммит |
|---|---|
| G3 Главная / «Мои тренировки» | `91086c9` |
| G4 QA + P1 (Tabbar на 320px) | `3979dd0` |
| Golden Journey E2E + сиды CI (`scripts/e2e_seed_all.sh`) | `07beb74` |

Проверка: pytest 1420 passed; ruff чисто; `tsc -b` + vite build; E2E на чистой БД в режиме CI —
23 passed, 4 skipped (карантин), 0 failed.

## ORCH-1 — кросс-девайсная оркестрация (#229)

Состояние задач — GitHub Issues (`status:*`), вид — `docs/PROJECT_STATUS.md` + закреплённый #230;
planner → worker → planner в Actions (`orch-*.yml`, `scripts/orch.py`), лимит 5 задач на пакет,
первый живой пакет запускает только владелец. Правила — `docs/AGENT_EXECUTION_MODEL.md` § Orchestration.

## Дальше

1. ~~Draft PR `develop/current` → `main` и CI (#222)~~ — PR #226 (draft), CI зелёный.
2. ~~Staging (#223)~~ — `4610cb6` выкачен на staging 2026-09-29, миграция до `c3d4e5f6a7b8`, health/статика/auth-границы
   проверены; аутентифицированный E2E против staging недоступен (нужен staging BOT_TOKEN + сид БД).
   → QA на реальном iPhone (#224, чек-лист `docs/IPHONE_QA_CHECKLIST.md`) → P0/P1 → production.

Известный долг: монеты/ачивки v2 (#225; см. `PROJECT_SPEC.md §6`); сходимость legacy/v2
прогрессии и истории; скорость pytest; намеренно закарантиненные устаревшие E2E
(`plans-manual-session`, `plans-start-session`, `journal-combined`, `plans-grouping`).

## Как вести работу

1. Перед кодом — гейт из `CLAUDE.md` (ветка/HEAD/дерево, `PROJECT_SPEC`, этот файл, нужные
   skills, реальный код, конфликты → стоп на нерешённом продуктовом вопросе).
2. Нетривиальная схема/прогрессия — план с числами до кода (конституция, Принцип II).
3. Миграции только аддитивные (`.claude/skills/migrations-safe`), проверка на непустых таблицах.
4. Чекпойнты небольшие: сфокусированные тесты → коммит → **push**. Полный набор — на
   значимых интеграционных точках, не после каждой правки.
5. Тест, ловящий баг, доказывается откатом исправления (Принцип IV).
6. Поведение изменилось → обновить `PROJECT_SPEC.md` в том же PR; неочевидное/ловушки →
   `docs/ENGINEERING_NOTES.md`.

## Отчёт о проверке (R1–R4)

- Бэкенд: полный набор на R3 — 1403 passed, 1 failed (`test_admin_broadcast` album — флейк базы,
  падает и на `830f205`); `ruff check app tests scripts` чисто.
- Фронтенд: `tsc -b` + `vite build` чисто.
- Браузерный QA (реальные FastAPI + Postgres + Chromium/Playwright): `builder-execution` (6 сценариев:
  reps/time/max/interval/смешанный/дубли), `journal-v2`, `analytics-v2` (4, включая 320/390 px).

## ORCH-2 — GitHub owner UI

Owner-comment dispatcher on main → existing planner/worker on develop/current.
Controls, safety boundaries and sandbox proof: [ORCH_OWNER_UI.md](ORCH_OWNER_UI.md).
