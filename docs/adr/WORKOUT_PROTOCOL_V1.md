# ADR: Workout Protocol v1 (Phase A1, issue #188)

**Статус:** Accepted. **Дата:** 2026-09-22.

## Контекст

Существующий `_resolve_plain_exercise_block` (app/services/live_session.py) хардкодит «3 подхода × target 0» для любого упражнения вне STEP-программы/комплекса — реальные протоколы («3 минуты подтягиваний» интервалом, «Планка» на время, «Отжимания» на повторения) в текущей схеме не представимы. Полный аудит и design contract — см. историю issue #188 (Product Structure Reset, Phase A0 design contract v0/v1).

## Решение

**Product ≠ Technical storage.**

| Продукт | Техническое хранилище |
|---|---|
| Workout | `complexes` (таблица `Complex`) — **без rename** |
| WorkoutItem | `complex_items` (таблица `ComplexItem`) — **без rename** |

**Canonical references — уже существующие, новых FK не создано:**
- `PlanItem.complex_id`
- `ProgramItem.complex_id`
- `SessionBlock.complex_id`

## Definition protocol vs Resolved protocol

Два структурно разных набора Pydantic-типов (`app/domain/workout_protocol.py`):

- **Definition** — что настроил автор Workout. `prescription.source: "static"|"progression"`. При `static` — конкретные числа в definition. При `progression` — чисел нет вовсе (не nullable, отсутствуют как ветка union).
- **Resolved** — что конкретно должен выполнить пользователь сейчас. Структурно **не может** содержать `prescription`/`source` (`ConfigDict(extra="forbid")` + отсутствие полей).

4 типа: `reps_sets`, `time_sets`, `max_effort`, `interval`. Схема расширяется новыми вариантами union (AMRAP/EMOM/circuit — не реализованы в Phase A1) без миграции существующих строк.

## Progression boundary

`app/domain/workout_snapshot.py::build_workout_snapshot` — единственная точка перехода definition → resolved. Принимает `ProgressionResolver: Callable[[int], list[int]]` — простую функцию `exercise_id → target_reps по подходам`. **Builder никогда не импортирует** `StepProgressionStrategy`/`ProgramInclusion`/`block_a`/`block_b` — подтверждено архитектурным тестом (`test_builder_does_not_import_progression_internals`, AST-анализ реальных импортов, не substring-поиск по докстрингам).

Session engine (будущая волна) получает только `WorkoutSnapshot` — никогда не видит `prescription`/`source`.

## Interval semantics

Для `total_duration_seconds=180, work_seconds=10, rest_seconds=20`: `WORK 0–10, REST 10–30, ..., WORK 150–160, REST 160–180, DONE at 180`. Заканчивается **точно** в `total_duration_seconds`, не продлевая текущую фазу. `completed_cycles` (для будущего `SessionBlock.result`, не реализовано в Phase A1) = число **полностью завершённых WORK-фаз**, не WORK+REST пар.

## Legacy compatibility

`ComplexItem`'s старые поля (`sets`/`target_value`/`target_unit`/`rest_seconds`) не удалены, остаются compatibility path. `_resolve_plain_exercise_block`/STEP-путь не изменены — не подключены к Workout-модели в Phase A1, сосуществуют.

## Storage (миграция `5f6a7b8c9d0e`, аддитивная)

- `ComplexItem.protocol: JSONB NULL`
- `Complex.source_type: String(20) NOT NULL DEFAULT 'system'` (`"system"|"user"`)
- `Complex.owner_user_id: BigInteger NULL FK users.id ON DELETE CASCADE`

Invariant (`system` → `owner_user_id IS NULL`, `user` → `owner_user_id IS NOT NULL`) — сервисный слой, не DB CHECK (проект нигде не использует CHECK-констрейнты для похожих инвариантов, см. `ProgramItem` "ровно одно из exercise_id/complex_id").

## Что НЕ сделано в Phase A1 (осознанно)

Session interval engine, UI, Workout Builder, миграция `PlanItem`/`Program` на использование Workout вместо прямых `exercise_id`, rename таблиц, archive-механизм для Workout, `SessionBlock.result` для interval-фактов, HTTP `/workouts` API.
