from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workout
from app.db.repositories.workout_sets import WorkoutSetRepository


async def delete_noncascade_workout(session: AsyncSession, workout: Workout) -> None:
    """Удаляет тренировку, НЕ участвующую в каскаде (бэкдейт/свободные
    подтягивания, issue #146) — единственный случай, для которого удаление
    однозначно безопасно: такие записи не входят в _cascade_chain, значит
    удаление не оставляет "дыру" в последовательности sequence_number и не
    требует пересчёта target/прогрессии соседних тренировок (тот же
    инвариант, что уже использует edit_noncascade_workout, issue #106).
    Удаление ОБЫЧНЫХ тренировок цепочки каскада сюда намеренно не входит —
    решение, пересчитывать ли каскад при их удалении, требует явного
    согласования продукта (см. issue #146), не принято молча.

    Архивирует (не удаляет молча) — переиспользует существующие
    workouts_archive_admin_reset/blocks_archive_admin_reset (миграция
    b41882a0e3e8, тот же принцип "Архивировать, не удалять", что и у
    "🧪 Полный сброс", app/services/admin_reset.py): это не копия той
    функции под другим именем, а осознанное переиспользование уже
    поддерживаемого в актуальном состоянии слепка схемы workouts/blocks —
    заводить второй набор архивных таблиц под ещё один сценарий "не терять
    удалённые строки" означало бы дублировать то же самое обязательство
    синхронизации при каждом ALTER TABLE (см. правило в CLAUDE.md про
    список из пяти *_archive_admin_reset таблиц), не давая ничего взамен."""
    if workout.participates_in_cascade:
        raise ValueError("cannot delete a workout that participates in the cascade")

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
        # его здесь молча — см. обсуждение в issue #146.
        workout_set = await WorkoutSetRepository(session).get_by_id(workout.workout_set_id)
        if workout_set is not None and workout_set.workouts_completed > 0:
            workout_set.workouts_completed -= 1

    await session.flush()
