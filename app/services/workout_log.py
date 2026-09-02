from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BlockType, EquipmentType, Workout, WorkoutSet, WorkoutSetStatus
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.achievements import (
    AchievementCode,
    check_equipment_changed,
    check_first_weighted_pullup,
    check_set_completed,
)
from app.domain.session import BlockLog
from app.services.achievement_checks import unlock_history_achievements, unlock_volume_milestones
from app.services.gamification import GamificationService


async def ensure_active_workout_set(session: AsyncSession, user_id: int) -> WorkoutSet | None:
    """Сет закрывается автоматически по достижении SET_LENGTH тренировок
    (WorkoutSetRepository.increment_completed) — раньше это означало тупик
    "нет активного сета, напишите в поддержку". Сеты — это просто окно
    отчётности на 12 тренировок, они не должны блокировать тренировки,
    поэтому следующий сет открывается автоматически от последнего замера.

    Публичная функция сервисного слоя (issue #36, Этап 1 Mini App) — нужна
    и боту (app/bot/handlers/workout.py), и веб-слою (app/web/routes.py),
    единственный источник, не копия."""
    workout_sets = WorkoutSetRepository(session)
    active = await workout_sets.get_active_for_user(user_id)
    if active is not None:
        return active

    baseline = await BaselineRepository(session).get_latest_for_user(user_id)
    if baseline is None:
        return None
    return await workout_sets.create(user_id=user_id, started_from_baseline_id=baseline.id)


# Сумма за COINS_PER_WORKOUT не определена (см. app/services/onboarding.py)
# — начисляем 0, но фиксируем сам факт тренировки, чтобы история работала
# уже сейчас. EQUIPMENT_CHANGED/SET_COMPLETED/FIRST_WEIGHTED_PULLUP —
# суммы утверждены (Часть 10 / ревизия ачивок).
COINS_PER_WORKOUT = 0
EQUIPMENT_CHANGED_COINS = 30
SET_COMPLETED_COINS = 200
FIRST_WEIGHTED_PULLUP_COINS = 100


class WorkoutLogService:
    """Оркестрирует запись тренировки: сама тренировка (WorkoutRepository,
    с его каскадом и sequence_number) + событие в аналитику + монеты за
    тренировку + проверка ачивок, которые можно определить прямо здесь.

    EQUIPMENT_CHANGED, SET_COMPLETED и FIRST_WEIGHTED_PULLUP разблокируются
    прямо из результата записи (см. _unlock_workout_achievements — только
    для record_workout, требуют каскада/сета). TEN_WORKOUTS_STREAK,
    MAX_REPS_PLUS_TEN, MONTH_NO_GAPS и пороги объёма (VOLUME_*) считаются
    из полной истории (app.services.achievement_checks) — им каскад не
    нужен, поэтому проверяются после ЛЮБОЙ записи, включая бэкдейт и
    свободные подтягивания."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workouts = WorkoutRepository(session)
        self._workout_sets = WorkoutSetRepository(session)
        self._events = EventRepository(session)
        self._gamification = GamificationService(session)

    async def record_workout(
        self,
        *,
        user_id: int,
        workout_set_id: int,
        performed_at: datetime,
        block_a_reps: BlockLog,
        block_b_reps: BlockLog,
        block_a_equipment_type: EquipmentType,
        block_a_equipment_value: Decimal | None,
        block_b_equipment_type: EquipmentType,
        block_b_equipment_value: Decimal | None,
        block_a_equipment_item_id: int | None = None,
        block_b_equipment_item_id: int | None = None,
        target_a_override: int | None = None,
        target_b_override: int | None = None,
        is_deload_a: bool = False,
        comment: str | None = None,
    ) -> Workout:
        workout = await self._workouts.record_workout(
            user_id=user_id,
            workout_set_id=workout_set_id,
            performed_at=performed_at,
            block_a_reps=block_a_reps,
            block_b_reps=block_b_reps,
            block_a_equipment_type=block_a_equipment_type,
            block_a_equipment_value=block_a_equipment_value,
            block_b_equipment_type=block_b_equipment_type,
            block_b_equipment_value=block_b_equipment_value,
            block_a_equipment_item_id=block_a_equipment_item_id,
            block_b_equipment_item_id=block_b_equipment_item_id,
            target_a_override=target_a_override,
            target_b_override=target_b_override,
            is_deload_a=is_deload_a,
            comment=comment,
        )

        await self._events.create(
            user_id=user_id, event_type="workout_completed", payload={"workout_id": workout.id},
        )
        await self._gamification.award_workout_coins(user_id, COINS_PER_WORKOUT)
        await self._unlock_workout_achievements(user_id, workout)
        await unlock_history_achievements(self._session, user_id, now=datetime.now(UTC))
        await unlock_volume_milestones(self._session, user_id)
        return workout

    async def record_backdated_workout(
        self,
        *,
        user_id: int,
        workout_set_id: int,
        performed_at: datetime,
        block_a_reps: BlockLog,
        block_b_reps: BlockLog,
        block_a_equipment_type: EquipmentType,
        block_a_equipment_value: Decimal | None,
        block_b_equipment_type: EquipmentType,
        block_b_equipment_value: Decimal | None,
        block_a_equipment_item_id: int | None = None,
        block_b_equipment_item_id: int | None = None,
        comment: str | None = None,
    ) -> Workout:
        """Не участвует в каскаде (см. WorkoutRepository.record_backdated_workout),
        поэтому и ачивки на переход снаряда/закрытие сета здесь не
        проверяем — closing a set задним числом можно, но статус сета
        WorkoutSetRepository.increment_completed уже обновит сам.
        TEN_WORKOUTS_STREAK/MONTH_NO_GAPS/MAX_REPS_PLUS_TEN и пороги
        объёма от каскада не зависят — проверяем и здесь (см.
        app.services.achievement_checks)."""
        workout = await self._workouts.record_backdated_workout(
            user_id=user_id,
            workout_set_id=workout_set_id,
            performed_at=performed_at,
            block_a_reps=block_a_reps,
            block_b_reps=block_b_reps,
            block_a_equipment_type=block_a_equipment_type,
            block_a_equipment_value=block_a_equipment_value,
            block_b_equipment_type=block_b_equipment_type,
            block_b_equipment_value=block_b_equipment_value,
            block_a_equipment_item_id=block_a_equipment_item_id,
            block_b_equipment_item_id=block_b_equipment_item_id,
            comment=comment,
        )
        await self._events.create(
            user_id=user_id, event_type="workout_backdated", payload={"workout_id": workout.id},
        )
        await unlock_history_achievements(self._session, user_id, now=datetime.now(UTC))
        await unlock_volume_milestones(self._session, user_id)
        return workout

    async def record_free_workout(
        self,
        *,
        user_id: int,
        workout_set_id: int,
        performed_at: datetime,
        block_a_reps: BlockLog,
        equipment_type: EquipmentType,
        equipment_value: Decimal | None = None,
        equipment_item_id: int | None = None,
        comment: str | None = None,
    ) -> Workout:
        """"➕ Внести свободные подтягивания" (Часть 10, пакет #2, п.21) —
        вне каскада и вне сета из 12 (см.
        WorkoutRepository.record_free_workout), поэтому монеты за
        тренировку и EQUIPMENT_CHANGED/SET_COMPLETED здесь не проверяем,
        как и для record_backdated_workout. Но объём и историю (стрик,
        месяц без пропусков, макс. вырос) свободные подтягивания меняют
        так же, как обычная тренировка — проверяем."""
        workout = await self._workouts.record_free_workout(
            user_id=user_id, workout_set_id=workout_set_id, performed_at=performed_at,
            block_a_reps=block_a_reps, equipment_type=equipment_type,
            equipment_value=equipment_value, equipment_item_id=equipment_item_id, comment=comment,
        )
        await self._events.create(
            user_id=user_id, event_type="free_workout_recorded",
            payload={"workout_id": workout.id, "volume": block_a_reps.volume},
        )
        await unlock_history_achievements(self._session, user_id, now=datetime.now(UTC))
        await unlock_volume_milestones(self._session, user_id)
        return workout

    async def _unlock_workout_achievements(self, user_id: int, workout: Workout) -> None:
        block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
        block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

        if block_b.equipment_type == EquipmentType.WEIGHT:
            history = await self._workouts.list_for_user(user_id)
            weighted_workouts = [
                w for w in history
                if any(b.block_type == BlockType.B and b.equipment_type == EquipmentType.WEIGHT for b in w.blocks)
            ]
            is_first_weighted = len(weighted_workouts) == 1  # только та, что мы сейчас записали
            if check_first_weighted_pullup(is_first_weighted):
                await self._gamification.unlock_achievement(
                    user_id=user_id, code=AchievementCode.FIRST_WEIGHTED_PULLUP,
                    coins_reward=FIRST_WEIGHTED_PULLUP_COINS,
                )

        if check_equipment_changed(block_a.equipment_changed or block_b.equipment_changed):
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.EQUIPMENT_CHANGED, coins_reward=EQUIPMENT_CHANGED_COINS,
            )

        workout_set = await self._workout_sets.get_by_id(workout.workout_set_id)
        just_completed = workout_set.status == WorkoutSetStatus.COMPLETED
        if check_set_completed(just_completed):
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.SET_COMPLETED, coins_reward=SET_COMPLETED_COINS,
            )
