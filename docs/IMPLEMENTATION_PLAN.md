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

## Дальше

1. **G3** — Home/«Мои тренировки»: discovery UI.
2. **G4** — итоговый продуктовый QA + ограниченные P0/P1.
3. **Golden Journey** — постоянный современный E2E в CI (#221), затем PR/CI (#222).
4. Staging (#223) → QA на реальном iPhone (#224) → P0/P1 → production.

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
