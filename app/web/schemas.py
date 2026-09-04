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


class HistoryEntryResponse(BaseModel):
    """Одна тренировка в списке "История" (issue #50, волна 1) — тот же
    набор фактов, что печатает app.bot.handlers.history.format_history_entry,
    просто структурированный для карточки, а не единый текстовый блок.
    target_a/target_b заполнены только у самой свежей записи во всей
    истории (is_latest в format_history_entry) — у более ранних это число
    уже неактуально после следующей тренировки.

    workout_id (issue #52) — нужен фронтенду, чтобы открыть
    GET/PATCH /api/history/{workout_id} по тапу на карточку; is_backdated
    здесь эквивалентно "не редактируется" (см. app.bot.handlers.workout_edit::
    _is_editable — для завершённой тренировки participates_in_cascade=False
    означает и sequence_number is None), отдельного is_editable не заводим,
    чтобы не дублировать один и тот же факт двумя полями."""

    workout_id: int
    performed_at: str
    is_backdated: bool
    comment: str | None
    equipment_a: EquipmentInfo
    equipment_b: EquipmentInfo
    result_a: str
    result_b: str
    target_a: int | None = None
    target_b: int | None = None


class HistoryResponse(BaseModel):
    """GET /api/history — самые свежие тренировки первыми, offset/limit
    пагинация (issue #50: не грузить всю историю разом на клиент)."""

    items: list[HistoryEntryResponse]
    has_more: bool


class ProgressPointResponse(BaseModel):
    """Одна точка графика прогресса (issue #50, волна 2) — цель за подход
    блока A/Б на момент этой тренировки (BlockAssignment.target_after, уже
    посчитанный app.domain.progression, здесь не пересчитывается)."""

    performed_at: str
    target_a: int
    target_b: int
    workout_set_id: int | None


class ProgressResponse(BaseModel):
    points: list[ProgressPointResponse]


class SubscriptionResponse(BaseModel):
    """Раздел подписки/оплаты Mini App (issue #53, волна 1) — тот же
    format_subscription_status, что "Профиль" (app/web/routes.py::get_profile),
    расширенный полями оплаты. status — сырое значение
    app.db.models.SubscriptionStatus ("none"/"trial"/"active"/"expired"),
    status_label — готовый текст для отображения, оба вместе (не только
    label), чтобы фронтенд мог решить, показывать ли блок "Тарифы и
    реквизиты" (see pricing_text_html) отдельно от текста статуса.

    pricing_text_html — app.bot.texts.PRICING_TEXT как есть, без
    пересборки в отдельные JSON-поля: реквизиты (ИНН/ОГРН) уже согласованы
    с модерацией Робокассы, дублирование их в структурированном виде
    развело бы два источника при следующей правке текста. Источник
    полностью статический (не пользовательский ввод) — безопасен для
    рендера как HTML на фронтенде.

    is_onboarded=False — единственный случай, когда остальные поля пустые
    (тот же принцип, что у ProfileResponse/HelloResponse); price_rub/days/
    pricing_text_html/robokassa_available заполнены всегда, они не зависят
    от того, онбордился ли пользователь."""

    is_onboarded: bool
    status: str | None = None
    status_label: str | None = None
    expires_at: str | None = None
    price_rub: int
    days: int
    pricing_text_html: str
    robokassa_available: bool


class PaymentLinkResponse(BaseModel):
    payment_url: str


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


class HistoryBlockDetail(BaseModel):
    """Один блок исторической записи для формы редактирования (issue #52)
    — working_reps/max_reps как реально введены (их длина уже кодирует
    число рабочих подходов на момент ТОЙ тренировки, отдельного work_sets
    не нужно, см. app.bot.handlers.workout_edit::_start_editing).
    target_before — то же число, от которого реально считался ввод (не
    текущая цель пользователя, если редактируется старая запись)."""

    working_reps: list[int]
    max_reps: int
    target_before: int
    equipment: EquipmentInfo


class HistoryEditDetailResponse(BaseModel):
    """GET /api/history/{workout_id} — данные для предзаполнения формы
    редактирования. is_editable — тот же app.bot.handlers.workout_edit::
    _is_editable (внесённые задним числом/не участвующие в каскаде записи
    не редактируются через этот путь), импортируется напрямую, не
    дублируется."""

    workout_id: int
    performed_at: str
    is_editable: bool
    comment: str | None
    block_a: HistoryBlockDetail
    block_b: HistoryBlockDetail


class HistoryEditRequest(BaseModel):
    """PATCH /api/history/{workout_id} — тот же смысл полей, что
    WorkoutSubmitRequest (issue #36/#45/#48), только без confirm/comment
    по умолчанию не переписывает существующий (см. app/web/routes.py:
    edit_history_workout — comment=None оставляет прежний текст, как и
    app.bot.handlers.workout_edit, которая правку комментария вообще не
    предлагает)."""

    block_a_working_reps: list[Reps] = Field(min_length=1)
    block_a_max_reps: Reps
    block_b_working_reps: list[Reps] = Field(min_length=1)
    block_b_max_reps: Reps
    block_a_actual_weight: Decimal | None = Field(default=None, gt=0)
    block_b_actual_weight: Decimal | None = Field(default=None, gt=0)
    block_a_actual_band_item_id: int | None = None
    block_b_actual_band_item_id: int | None = None
    comment: str | None = None
    confirm_anomalies: bool = False


class TimerStartRequest(BaseModel):
    """POST /api/timer/start (issue #59, волна 1) — timer_type проверяется
    на сервере против app.db.models.ActiveTimerType (см. app/web/routes.py::
    _parse_timer_type), невалидное значение — 400, не тихая запись мусора.
    duration_seconds ограничен сверху 3600 (час) — продуктовая защита от
    мусорных значений с клиента, не физический факт: самый длинный
    реальный таймер в потоке тренировки (issue) — "большой перерыв" между
    блоками A и Б, а не отдых между подходами."""

    timer_type: str
    duration_seconds: int = Field(ge=1, le=3600)
    block_letter: str | None = Field(default=None, pattern="^[AB]$")
    set_number: int | None = Field(default=None, ge=1)


class TimerStatusResponse(BaseModel):
    """Общий ответ для POST /api/timer/start, GET /api/timer/status и
    DELETE /api/timer — active=False, когда активного таймера нет ВООБЩЕ
    (пользователь не онбордился или ещё не стартовал ни одного) или когда
    он уже истёк (remaining_seconds достиг 0 — сервер не удаляет
    истёкшую запись при чтении, см. app/web/routes.py); остальные поля
    заполнены в обоих случаях "запись есть", только remaining_seconds
    отличает "идёт" от "истёк"."""

    active: bool
    timer_type: str | None = None
    duration_seconds: int | None = None
    remaining_seconds: int | None = None
    block_letter: str | None = None
    set_number: int | None = None


class BackdateSubmitRequest(BaseModel):
    """POST /api/workout/backdate (issue #52) — снаряд здесь ВСЕГДА явный
    (не наследуется молча из прогрессии, в отличие от WorkoutSubmitRequest)
    — тот же принцип, что _begin_equipment_setup(target_a_state=None, ...)
    у бота для бэкдейта (app/bot/handlers/backdate.py): пропущенная
    тренировка могла пройти на другом снаряде, наследование по умолчанию
    было бы неверным по умолчанию, не просто менее удобным.

    performed_at — "YYYY-MM-DD", без времени (тот же уровень точности, что
    и календарь бэкдейта бота — время дня внесённой задним числом
    тренировки не имеет значения для прогрессии)."""

    performed_at: str
    block_a_working_reps: list[Reps] = Field(min_length=1)
    block_a_max_reps: Reps
    block_b_working_reps: list[Reps] = Field(min_length=1)
    block_b_max_reps: Reps
    block_a_equipment_type: str
    block_a_equipment_value: Decimal | None = Field(default=None, gt=0)
    block_a_equipment_item_id: int | None = None
    block_b_equipment_type: str
    block_b_equipment_value: Decimal | None = Field(default=None, gt=0)
    block_b_equipment_item_id: int | None = None
    comment: str | None = None
    confirm_anomalies: bool = False
