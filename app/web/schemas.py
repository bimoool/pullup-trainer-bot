from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from app.bot.parsing import MAX_REPS, MIN_REPS


class HelloResponse(BaseModel):
    name: str
    is_onboarded: bool
    readiness_status: str | None
    days_since_last_workout: int | None


class EquipmentInfo(BaseModel):
    """Снаряд блока, каким он унаследован с прошлой тренировки
    (needs_new_equipment=False — иначе GET /api/workout/plan вообще не
    дошёл бы до статуса "ready", см. app/web/routes.py). label — тот же
    текст, что видит пользователь бота (app.bot.formatting.format_equipment_label,
    не отдельная веб-копия форматирования)."""

    type: str
    value: Decimal | None
    item_id: int | None
    label: str


class BandItemInfo(BaseModel):
    """Один пункт личного списка резин пользователя (app.db.models.EquipmentItem)
    — тот же источник, что band_item_picker_keyboard бота
    (app/bot/keyboards.py). resistance_kg опционален (см. докстринг модели:
    резины в залах часто без маркировки)."""

    id: int
    name: str
    resistance_kg: Decimal | None


class WorkoutPlanResponse(BaseModel):
    """GET /api/workout/plan — статус определяет, есть ли форма ввода:
    "ready" — да, план ниже заполнен; любой другой статус — форма не
    показывается, поля плана пустые (см. issue #36, сужение скоупа
    Этапа 1: только обычная тренировка и gap_rollback, остальные случаи
    ведут в бота).

    band_items заполняется, только если равнозначный ввод резины возможен
    хотя бы для одного блока (equipment_a/b.type == "band") — личный список
    пользователя (app/bot/keyboards.py::band_item_picker_keyboard читает
    тот же EquipmentItemRepository.list_for_user), пустой список иначе."""

    status: str
    workout_set_id: int | None = None
    target_a: int | None = None
    target_b: int | None = None
    work_sets_a: int | None = None
    work_sets_b: int | None = None
    equipment_a: EquipmentInfo | None = None
    equipment_b: EquipmentInfo | None = None
    is_gap_rollback: bool = False
    band_items: list[BandItemInfo] = Field(default_factory=list)


Reps = Annotated[int, Field(ge=MIN_REPS, le=MAX_REPS)]
# Те же границы, что app.bot.parsing.parse_reps проверяет для живого ввода
# в боте — единственный источник (MAX_REPS=999, см. CLAUDE.md), не
# отдельная веб-константа.


class WorkoutSubmitRequest(BaseModel):
    block_a_working_reps: list[Reps] = Field(min_length=1)
    block_a_max_reps: Reps
    block_b_working_reps: list[Reps] = Field(min_length=1)
    block_b_max_reps: Reps
    # Необязательная правка веса на месте (issue #45, часть 2) — тот же
    # смысл, что "✏️ Изменить вес/резину" в боте (app/bot/handlers/workout.py::
    # handle_change_block_equipment): снаряд наследуется из прогрессии
    # молча, пользователь мог реально взять другой вес. Заполняется только
    # если фактический вес отличается от предложенного в плане; применяется
    # (см. app/web/routes.py::submit_workout), только когда контекст на
    # сервере подтвердил тип блока WEIGHT — то же самое ограничение, что у
    # бота (равнозначный ввод недоступен для BAND/BODYWEIGHT/AUSTRALIAN).
    block_a_actual_weight: Decimal | None = Field(default=None, gt=0)
    block_b_actual_weight: Decimal | None = Field(default=None, gt=0)
    # Выбор резины (issue #48) — тот же принцип, что actual_weight выше,
    # только для BAND: применяется (см. app/web/routes.py::submit_workout),
    # только когда контекст на сервере подтвердил тип блока BAND, и только
    # если item реально принадлежит вызывающему пользователю (проверка в
    # routes.py — id из личного списка другого пользователя недопустим).
    block_a_actual_band_item_id: int | None = None
    block_b_actual_band_item_id: int | None = None
    comment: str | None = None
    confirm_anomalies: bool = False


class AnomalyFlagsResponse(BaseModel):
    """Зеркало app.domain.anomalies.AnomalyFlags для JSON — та же функция
    detect_anomalies, что использует бот, просто сериализованный результат."""

    large_value: int | None = None
    previous_avg: float | None = None
    current_avg: float | None = None
    expected_set_count: int | None = None
    actual_set_count: int | None = None


class ProfileResponse(BaseModel):
    """Вкладка "Профиль" Mini App (issue #45, часть 3) — узкий срез того,
    что показывает app.bot.handlers.menu.render_profile: тот же
    format_subscription_status, но без роста/веса/таймзоны/списка ачивок
    текстом — сознательно маленький первый шаг под навигацию, не перенос
    всего профиля бота. is_onboarded=False — единственный случай, когда
    остальные поля пустые (тот же принцип, что у HelloResponse)."""

    is_onboarded: bool
    subscription_status_label: str | None = None
    coins_balance: int | None = None
    achievements_count: int | None = None
    workouts_count: int | None = None
    days_since_last_workout: int | None = None


class WorkoutSubmitResponse(BaseModel):
    status: str
    target_a: int | None = None
    target_b: int | None = None
    equipment_a: EquipmentInfo | None = None
    equipment_b: EquipmentInfo | None = None
    result_a: str | None = None
    result_b: str | None = None
    anomalies_a: AnomalyFlagsResponse | None = None
    anomalies_b: AnomalyFlagsResponse | None = None
