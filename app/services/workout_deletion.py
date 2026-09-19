from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workout
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository


async def _archive_and_delete(session: AsyncSession, workout: Workout) -> None:
    """SQL-часть, общая для обоих путей удаления (issue #146) — архивирует
    в существующие workouts_archive_admin_reset/blocks_archive_admin_reset
    (тот же слепок схемы, что у "🧪 Полный сброс", см. докстрайты ниже) и
    удаляет саму строку workouts (blocks удаляются вслед за ней через
    ON DELETE CASCADE на workout_id, см. app.db.models.Block)."""
    params = {"workout_id": workout.id}
    await session.execute(
        text(
            "INSERT INTO blocks_archive_admin_reset "
            "SELECT * FROM blocks WHERE workout_id = :workout_id",
        ),
        params,
    )
    await session.execute(
        text(
            "INSERT INTO workouts_archive_admin_reset "
            "SELECT * FROM workouts WHERE id = :workout_id",
        ),
        params,
    )
    await session.execute(text("DELETE FROM workouts WHERE id = :workout_id"), params)


async def delete_cascade_workout(session: AsyncSession, workout: Workout) -> None:
    """Удаляет ОБЫЧНУЮ (каскадную) тренировку (issue #146, решение Кирилла —
    вариант A). Реальный кейс из комментария к issue: тренировка
    задублирована по ошибке — без пересчёта каскада дубль продолжал бы
    искажать прогрессию целей задним числом у всех последующих тренировок
    цепочки, само удаление не решало бы проблему дубля.

    Пересчёт (WorkoutRepository.recalculate_cascade_on_delete — см. её
    докстринг за подробным разбором механики и рисков смены снаряда
    посреди цепочки) выполняется ДО архивирования/удаления строки: ему
    нужно опросить _cascade_chain, пока сама запись ещё в БД, чтобы найти
    её позицию в цепочке.

    Архивирует, не удаляет молча — тот же принцип "Архивировать, не
    удалять" (app/services/admin_reset.py, "🧪 Полный сброс"), что и у
    delete_noncascade_workout ниже — не копия той функции под другим
    именем, а осознанное переиспользование уже поддерживаемого в актуальном
    состоянии слепка схемы workouts/blocks."""
    if not workout.participates_in_cascade:
        raise ValueError("cannot delete_cascade_workout a workout outside the cascade")

    await WorkoutRepository(session).recalculate_cascade_on_delete(workout)
    await _archive_and_delete(session, workout)
    await session.flush()


async def delete_noncascade_workout(session: AsyncSession, workout: Workout) -> None:
    """Удаляет тренировку, НЕ участвующую в каскаде (бэкдейт/свободные
    подтягивания, issue #146) — такие записи не входят в _cascade_chain,
    значит удаление не оставляет "дыру" в последовательности sequence_number
    и не требует пересчёта target/прогрессии соседних тренировок цепочки
    (тот же инвариант, что уже использует edit_noncascade_workout, issue
    #106). Обычные (каскадные) тренировки — см. delete_cascade_workout выше,
    вариант A из issue #146 (пересчёт каскада), решение Кирилла.

    Архивирует (не удаляет молча) — переиспользует существующие
    workouts_archive_admin_reset/blocks_archive_admin_reset (миграция
    b41882a0e3e8, тот же принцип "Архивировать, не удалять", что и у
    "🧪 Полный сброс", app/services/admin_reset.py): не копия той функции
    под другим именем, а осознанное переиспользование уже поддерживаемого в
    актуальном состоянии слепка схемы workouts/blocks — заводить второй
    набор архивных таблиц под ещё один сценарий "не терять удалённые
    строки" означало бы дублировать то же самое обязательство синхронизации
    при каждом ALTER TABLE (см. правило в docs/deploy.md про список из пяти
    *_archive_admin_reset таблиц), не давая ничего взамен."""
    if workout.participates_in_cascade:
        raise ValueError("cannot delete_noncascade_workout a workout that participates in the cascade")

    await _archive_and_delete(session, workout)

    if not workout.is_free_entry:
        # record_backdated_workout (в отличие от record_free_workout) сам
        # инкрементирует workout_sets.workouts_completed при создании —
        # без обратного decrement здесь счётчик навсегда останется
        # завышенным на 1, что перманентно сдвинет чётность is_heavy
        # (issue #97) для ВСЕХ последующих тренировок блока Б, не только
        # граничный случай закрытия сета ровно этой записью. Откат
        # WorkoutSetStatus.COMPLETED -> ACTIVE намеренно НЕ делается даже
        # если это тот самый редкий случай (запись закрыла сет ровно на
        # SET_LENGTH) — ensure_active_workout_set уже мог успеть открыть
        # следующий сет по любому обращению к плану между записью и
        # удалением, реоткрытие старого тогда означало бы два ACTIVE
        # сета одновременно у одного пользователя. Достаточно узкий и
        # непроверяемый без реального инцидента случай, чтобы не решать
        # его здесь молча — см. обсуждение в issue #146. Тот же приём для
        # каскадных тренировок — WorkoutRepository.recalculate_cascade_on_delete.
        workout_set = await WorkoutSetRepository(session).get_by_id(workout.workout_set_id)
        if workout_set is not None and workout_set.workouts_completed > 0:
            workout_set.workouts_completed -= 1

    await session.flush()
