from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def reset_user_progress(session: AsyncSession, user_id: int) -> None:
    """Админ-инструмент для тестирования (Часть 9 респека): архивирует (не
    удаляет) весь прогресс аккаунта — тот же принцип, что и в миграции
    34d73f5e17a4 (архивация дореспековских данных вместо удаления), только
    здесь это повторяемая операция, скоуп по одному user_id, в постоянные
    *_archive_admin_reset таблицы (см. миграцию b41882a0e3e8).

    Порядок DELETE — из-за FK без ON DELETE CASCADE (кроме blocks.workout_id,
    который каскадится сам): workouts (и вместе с ними blocks) ->
    workout_sets -> baselines -> equipment_items. Онбординговые поля users
    обнуляются в конце — аккаунт возвращается в состояние "до онбординга",
    /start заново поведёт через анкету и замер."""
    params = {"user_id": user_id}

    await session.execute(
        text(
            "INSERT INTO blocks_archive_admin_reset "
            "SELECT b.* FROM blocks b JOIN workouts w ON w.id = b.workout_id WHERE w.user_id = :user_id",
        ),
        params,
    )
    await session.execute(
        text("INSERT INTO workouts_archive_admin_reset SELECT * FROM workouts WHERE user_id = :user_id"),
        params,
    )
    await session.execute(
        text("INSERT INTO workout_sets_archive_admin_reset SELECT * FROM workout_sets WHERE user_id = :user_id"),
        params,
    )
    await session.execute(
        text("INSERT INTO baselines_archive_admin_reset SELECT * FROM baselines WHERE user_id = :user_id"),
        params,
    )
    await session.execute(
        text(
            "INSERT INTO equipment_items_archive_admin_reset SELECT * FROM equipment_items WHERE user_id = :user_id",
        ),
        params,
    )

    # workouts удаляются первыми — blocks.workout_id ON DELETE CASCADE
    # унесёт blocks автоматически, отдельный DELETE не нужен.
    await session.execute(text("DELETE FROM workouts WHERE user_id = :user_id"), params)
    await session.execute(text("DELETE FROM workout_sets WHERE user_id = :user_id"), params)
    await session.execute(text("DELETE FROM baselines WHERE user_id = :user_id"), params)
    await session.execute(text("DELETE FROM equipment_items WHERE user_id = :user_id"), params)

    await session.execute(
        text(
            "UPDATE users SET onboarding_completed_at = NULL, weight_kg = NULL, height_cm = NULL, "
            "gender = NULL, birth_date = NULL, timezone = NULL WHERE id = :user_id",
        ),
        params,
    )
    await session.flush()
