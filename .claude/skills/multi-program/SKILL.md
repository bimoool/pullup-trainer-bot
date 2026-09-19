---
name: multi-program
description: Текущее состояние многокурсовой платформы — какие волны сделаны, что где лежит, какие инварианты нельзя нарушать. Использовать для любой задачи, затрагивающей app/db/models_program.py, app/web/routes_v2*.py, ProgressionStrategy, TrainingPlan/ProgramInclusion, backfill или ветку feature/multi-program.
---

# Многокурсовая платформа

Цель — вместо одних подтягиваний держать несколько параллельных программ (курсов) с
комплексами упражнений. Делается волнами в ветке **`feature/multi-program`**, не в `main`.

## Состояние волн

| Волна | Issue | Что | Статус |
|---|---|---|---|
| 0 | #158 | `ProgressionStrategy` — интерфейс preview/apply | в ветке |
| 1 | #160 | миграции: Exercise/Complex/Program/TrainingPlan/ProgramInclusion/Session/Block/SetLog | в ветке |
| 2 | #163 | backfill: подтягивания как seed-Program, история в TrainingSession | в ветке |
| 3 | #165 | CRUD/read `/api/v2`, не подключены к UI | в ветке |
| 4 | #167 | Dashboard во фронтенде через `/api/v2` | в ветке, есть открытый баг |
| 5–8 | — | cutover, недельная матрица и далее | не начаты |

PR #171 (draft) — `feature/multi-program` → `main`, открыт ради прогона CI. Не мержить
без отдельного подтверждения владельца продукта.

## Инварианты

1. **Старая схема остаётся источником истины** до волны cutover. `app/db/models.py`,
   `app/web/routes.py::_resolve_plan_context`, экран `WorkoutScreen.tsx` не удалять и
   не отключать.
2. **`routes_v2.py` — общий CRUD-слой**, не pull-up-специфичный. Любая логика статусов
   конкретного экрана идёт в отдельный файл (образец: `routes_v2_dashboard.py`).
3. **`tests/test_web/test_v2_not_wired_to_ui.py`** — инвариант: фронтенд не трогает `/api/v2`
   нигде, кроме явного allowlist новых файлов Dashboard. Расширять allowlist осознанно,
   не удалять тест.
4. **Бэкфилл идемпотентен по пользователю** — маркер «мигрирован» это наличие `TrainingPlan`.
   Повторная проверка на staging требует `--truncate`.

## Главный класс багов

`progression_state` в `ProgramInclusion` обязан совпадать с тем, что для того же пользователя
возвращает `WorkoutRepository.resolve_next_targets` — поле в поле, включая снаряд и цель
обоих блоков, в том числе для пользователя без единой тренировки. Расхождение здесь тихое:
эндпоинты отдают валидный ответ, а цифры не те. Любая правка бэкфилла или стратегии
прогрессии обязана сопровождаться тестом именно на это сравнение.
