from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

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
    Этапа 1: только обычная тренировка, gap_rollback и (issue #105)
    ежемесячный тест на максимум блока A, остальные случаи ведут в бота).

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
    # Объяснение роста work_sets блока A ДО начала тренировки (issue #79) —
    # то же значение, что app.db.repositories.workouts.NextBlockState.
    # work_sets_growth_reason, отдаётся как есть, текст форматирует
    # фронтенд (тот же приём, что is_gap_rollback выше).
    work_sets_growth_reason: Literal["stall", "ceiling"] | None = None
    band_items: list[BandItemInfo] = Field(default_factory=list)
    # Чётная ("тяжёлая") тренировка блока Б (issue #97) — фиксированные
    # повторения, повышенный вес (уже подставлен в equipment_b.value, см.
    # app/web/routes.py::_resolve_plan_context); фронтенд меняет
    # формулировку формы блока Б на основании этого флага, парсинг ввода не
    # меняется (тот же принцип, что и у бота).
    is_heavy_b: bool = False
    # Ежемесячный тест на максимум блока на объём (issue #89, форма в Mini
    # App — issue #105) — target_a/work_sets_a/equipment_a теряют обычный
    # смысл при True: target_a всегда None (текст теста больше не называет
    # никакого ориентирующего числа, ни здесь, ни в боте), equipment_a
    # принудительно свой вес. Фронтенд показывает вместо обычной сетки
    # блока A один вопрос "сколько реально смог".
    is_deload_a: bool = False


Reps = Annotated[int, Field(ge=MIN_REPS, le=MAX_REPS)]
# Те же границы, что app.bot.parsing.parse_reps проверяет для живого ввода
# в боте — единственный источник (MAX_REPS=999, см. CLAUDE.md), не
# отдельная веб-константа.


class WorkoutSubmitRequest(BaseModel):
    # min_length=0 (не 1, как у блока B) — тест на максимум блока A (issue
    # #89/#105) вводится одним числом без раскладки по подходам, тот же
    # смысл, что parse_reps("15") в боте: working_reps=(), max_reps=15.
    block_a_working_reps: list[Reps] = Field(min_length=0)
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


class AchievementItem(BaseModel):
    """Один пункт списка ачивок (issue #66, п.1) — code для стабильного
    сопоставления на фронте (если понадобится иконка/поведение отдельно от
    текста), label — тот же app.domain.achievements.ACHIEVEMENT_LABELS, что
    и app.bot.handlers.menu.render_profile (единый источник подписи, не
    веб-копия текста)."""

    code: str
    label: str
    unlocked_at: str


class ProfileResponse(BaseModel):
    """Вкладка "Профиль" Mini App (issue #45, часть 3) — узкий срез того,
    что показывает app.bot.handlers.menu.render_profile: тот же
    format_subscription_status, но без роста/веса/таймзоны текстом —
    сознательно маленький первый шаг под навигацию, не перенос всего
    профиля бота. is_onboarded=False — единственный случай, когда остальные
    поля пустые (тот же принцип, что у HelloResponse).

    achievements (issue #66, п.1) — то же самое, что уже даёт
    achievements_count числом, только с деталями (код/лейбл/дата) для
    кликабельного счётчика на экране: пустой список — тот же случай, что
    achievements_count == 0, а не "не загрузилось"."""

    is_onboarded: bool
    subscription_status_label: str | None = None
    coins_balance: int | None = None
    achievements_count: int | None = None
    achievements: list[AchievementItem] = Field(default_factory=list)
    workouts_count: int | None = None
    days_since_last_workout: int | None = None


class GtoResponse(BaseModel):
    """GET /api/gto (issue #71) — разряд ГТО по подтягиванию, отдельная
    концепция от обычных ачивок (app.domain.gto, не AchievementRepository):
    статус, а не факт истории, всегда пересчитывается на лету из текущего
    пола/возраста/лучшего max_reps, ничего не хранится в БД.

    applicable=False — рассчитать нечего, reason объясняет почему (см.
    app.domain.gto.GtoStatus для полного списка причин: only_male,
    missing_gender/missing_birth_date, age_out_of_range, norm_data_missing,
    no_workouts) — фронтенд показывает соответствующий текст, а не молчаливый
    пустой раздел. Остальные поля заполнены только когда applicable=True."""

    applicable: bool
    reason: str | None = None
    age: int | None = None
    step_number: int | None = None
    rank: str | None = None
    best_max_reps: int | None = None
    bronze_threshold: int | None = None
    silver_threshold: int | None = None
    gold_threshold: int | None = None
    next_rank: str | None = None
    reps_to_next_rank: int | None = None


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
    """Одна точка графика прогресса (issue #82: переделано с плана на факт,
    было target_after — см. история issue #50, волна 2). value_a/value_b —
    фактический результат тренировки по выбранной metric, не плановая цель:

    - max_reps: BlockLog.best_set (лучший подход, рабочий или на максимум).
    - volume: BlockLog.volume (сумма повторений блока за тренировку).
    - strength: app.domain.constants.to_signed_load(equipment_type,
      equipment_value) блока Б, ТОЛЬКО для WEIGHT/BODYWEIGHT (свой вес — 0,
      отягощение — плюс) — переживает смену отягощения, в отличие от
      повторений на блоке Б (сбрасываются при каждой смене). Резина (BAND)
      исключена целиком (issue #110), тем же принципом, что уже применён к
      epley_progress (issue #96): реальное сопротивление резины физически
      неизвестно, сравнивать его с кг нельзя ни в каком виде, даже со знаком
      минус. value_a всегда null (метрика скоуплена на блок Б, см.
      CLAUDE.md); value_b — null для BAND/AUSTRALIAN (там либо неизвестное,
      либо отсутствующее число в кг)."""

    performed_at: str
    value_a: Decimal | None
    value_b: Decimal | None
    workout_set_id: int | None


class ProgressResponse(BaseModel):
    metric: str
    points: list[ProgressPointResponse]


class WeeklySummaryResponse(BaseModel):
    """Зеркало app.domain.reports.WeeklySummary для JSON (issue #66, п.2) —
    та же недельная сводка, что показывает кнопка "📊 Прогресс" бота
    (app/bot/handlers/reports.py::handle_show_progress_report)."""

    workout_count: int
    total_volume: int
    volume_change_pct: float | None
    equipment_changed_a: bool
    equipment_changed_b: bool


class EquipmentProgressResponse(BaseModel):
    """Зеркало app.domain.reports.EquipmentProgress — динамика объёма на
    текущем (последнем использованном) снаряде блока A/Б, тот же смысл, что
    "с этой резиной делал 40, сейчас 80" в тексте бота."""

    equipment: EquipmentInfo
    first_volume: int
    current_volume: int
    change_pct: float | None


class CycleVolumeResponse(BaseModel):
    """Зеркало app.domain.reports.CycleVolume — одна строка списка "📈
    Аналитика по всем циклам" бота (app/bot/handlers/reports.py::
    handle_show_all_cycles_analytics)."""

    workout_set_id: int
    workout_count: int
    total_volume: int
    volume_change_pct: float | None


class EpleyProgressResponse(BaseModel):
    """Зеркало app.domain.reports.EpleyProgress (issue #96) — оценочная сила
    блока Б по формуле Эпли. None (весь объект отсутствует в AnalyticsResponse)
    — нет веса тела в профиле или нет ни одной подходящей тренировки блока Б
    (только WEIGHT/BODYWEIGHT с зафиксированным максимумом — резина и
    AUSTRALIAN исключены, см. epley_progress)."""

    current_load_kg: float
    change_pct_vs_previous: float | None
    change_pct_vs_first: float | None


class AnalyticsResponse(BaseModel):
    """GET /api/analytics (issue #66, п.2) — те же вызовы
    app.domain.reports с теми же входными данными, что и кнопки
    "📊 Прогресс"/"📈 Аналитика по всем циклам" бота, просто в JSON вместо
    готового текста. has_data=False — тот же случай, что "история пуста" у
    бота (texts.HISTORY_EMPTY) — единственный случай, когда остальные поля
    пустые. equipment_progress_a/b — None только если истории вообще нет
    (has_data=False уже покрывает этот случай раньше, см.
    current_equipment_progress), при has_data=True они всегда заполнены.
    epley_progress (issue #96) — None и при has_data=True тоже, если нет
    веса тела в профиле или нет подходящей тренировки блока Б (см.
    epley_progress/EpleyProgressResponse) — единственное поле из этой
    группы, которое остаётся опциональным при has_data=True."""

    has_data: bool
    weekly: WeeklySummaryResponse | None = None
    equipment_progress_a: EquipmentProgressResponse | None = None
    equipment_progress_b: EquipmentProgressResponse | None = None
    epley_progress: EpleyProgressResponse | None = None
    total_volume: int | None = None
    cycle_count: int | None = None
    cycles: list[CycleVolumeResponse] = Field(default_factory=list)


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


class BandHelpResponse(BaseModel):
    """FAQ "Как выбрать резину" (issue #102) — тот же приём, что
    pricing_text_html у SubscriptionResponse: статический текст бота как
    есть, без пересборки в структурированные поля."""

    text_html: str


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
    # Записанная тренировка была тестом на максимум блока A (issue #89/#105)
    # — то же значение, что Block.is_deload. Фронтенд показывает заметку
    # "цель не менялась" на экране "Готово", тот же смысл, что
    # texts.VOLUME_DELOAD_DONE_SUFFIX у бота.
    is_deload_a: bool = False


class HistoryBlockDetail(BaseModel):
    """Один блок исторической записи для формы редактирования (issue #52)
    — working_reps/max_reps как реально введены (их длина уже кодирует
    число рабочих подходов на момент ТОЙ тренировки, отдельного work_sets
    не нужно, см. app.bot.handlers.workout_edit::_start_editing).
    target_before — то же число, от которого реально считался ввод (не
    текущая цель пользователя, если редактируется старая запись).

    reported_volume (issue #106) — не None только у блока Б бэкдейт-записи,
    введённой в режиме "только итог" (issue #88, working_reps в этом случае
    всегда пуст) — фронтенд использует именно это поле, чтобы понять, какую
    форму показать при правке (раскладку по подходам или итог+максимум), не
    заставляя переключать формат."""

    working_reps: list[int]
    max_reps: int
    reported_volume: int | None = None
    target_before: int
    equipment: EquipmentInfo


class HistoryEditDetailResponse(BaseModel):
    """GET /api/history/{workout_id} — данные для предзаполнения формы
    редактирования. is_editable (issue #106) — тренировки цепочки каскада
    (app.bot.handlers.workout_edit::_is_editable) ИЛИ внесённые не в цепочку
    (бэкдейт/свободные, participates_in_cascade=False) — те и другие теперь
    редактируются, просто разными методами репозитория (edit_workout с
    каскадным пересчётом vs edit_noncascade_workout без него, см.
    app/web/routes.py::_history_is_editable)."""

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
    предлагает).

    block_b_reported_volume (issue #106) — заполняется ТОЛЬКО при правке
    бэкдейт-записи, изначально введённой в режиме "только итог" (issue
    #88): тогда block_b_working_reps обязан быть пустым (см.
    _check_block_b_format), а block_b_max_reps — либо честный максимум,
    либо 0, если он не был зафиксирован (тот же смысл, что и при первом
    вводе, см. app.bot.handlers.backdate.py::handle_backdate_block_b_total_max_skip).
    Для обычных (не бэкдейт) и бэкдейт-записей с честной раскладкой это
    поле остаётся None, как и раньше."""

    block_a_working_reps: list[Reps] = Field(min_length=1)
    block_a_max_reps: Reps
    block_b_working_reps: list[Reps] = Field(default_factory=list)
    block_b_max_reps: Reps
    block_b_reported_volume: Reps | None = None
    block_a_actual_weight: Decimal | None = Field(default=None, gt=0)
    block_b_actual_weight: Decimal | None = Field(default=None, gt=0)
    block_a_actual_band_item_id: int | None = None
    block_b_actual_band_item_id: int | None = None
    comment: str | None = None
    confirm_anomalies: bool = False

    @model_validator(mode="after")
    def _check_block_b_format(self) -> "HistoryEditRequest":
        if self.block_b_reported_volume is None and not self.block_b_working_reps:
            raise ValueError("block_b_working_reps is required unless block_b_reported_volume is given")
        if self.block_b_reported_volume is not None and self.block_b_working_reps:
            raise ValueError("block_b_working_reps must be empty when block_b_reported_volume is given")
        return self


class WorkoutDraftRequest(BaseModel):
    """PUT /api/workout/draft (issue #61) — сохраняет накопленный прогресс
    живой тренировки после каждого завершённого подхода, не только при
    финальной отправке (см. app/web/routes.py::save_workout_draft). Клиент
    шлёт весь накопленный массив разом, не один подход за раз — тот же
    приём, что и апдейт таймера (TimerStartRequest — тоже upsert целиком).

    В отличие от WorkoutSubmitRequest, working_reps может быть короче
    итогового числа рабочих подходов (ещё не все введены) и max_reps может
    отсутствовать вовсе (шаг с максимумом ещё не пройден) — черновик
    фиксирует промежуточное состояние, не готовую к записи тренировку."""

    step_index: int = Field(ge=0)
    block_a_working_reps: list[Reps] = Field(default_factory=list)
    block_a_max_reps: Reps | None = None
    block_b_working_reps: list[Reps] = Field(default_factory=list)
    block_b_max_reps: Reps | None = None
    block_a_actual_weight: Decimal | None = Field(default=None, gt=0)
    block_b_actual_weight: Decimal | None = Field(default=None, gt=0)
    block_a_actual_band_item_id: int | None = None
    block_b_actual_band_item_id: int | None = None
    comment: str | None = None


class WorkoutDraftResponse(BaseModel):
    """GET/PUT/DELETE /api/workout/draft — active=False значит черновика
    нет (обычный старт с экрана "intro", как и раньше) — либо потому что
    ещё не начинали, либо потому что явно отменили/уже сдали тренировку
    (submit_workout удаляет черновик при успешной записи, см. routes.py).
    Остальные поля заполнены только при active=True, тот же принцип, что у
    TimerStatusResponse."""

    active: bool
    step_index: int | None = None
    block_a_working_reps: list[int] | None = None
    block_a_max_reps: int | None = None
    block_b_working_reps: list[int] | None = None
    block_b_max_reps: int | None = None
    block_a_actual_weight: Decimal | None = None
    block_b_actual_weight: Decimal | None = None
    block_a_actual_band_item_id: int | None = None
    block_b_actual_band_item_id: int | None = None
    comment: str | None = None


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


class TimerPreferencesResponse(BaseModel):
    """GET/PUT /api/timer/preferences (issue #59, волна 2; sound_volume_percent
    — issue #90) — значения уже резолвлены дефолтом
    (app.domain.constants.DEFAULT_REST_SECONDS_BLOCK_A/B/
    DEFAULT_BIG_BREAK_SECONDS/DEFAULT_TIMER_SOUND_VOLUME_PERCENT), если
    пользователь ничего не настраивал — фронтенду не нужно знать про
    дефолты отдельно."""

    rest_seconds_block_a: int
    rest_seconds_block_b: int
    big_break_seconds: int
    sound_volume_percent: int


class TimerPreferencesUpdateRequest(BaseModel):
    """PUT /api/timer/preferences — сохраняет ровно одну настройку за раз, не
    молча при каждом сдвиге ползунка на экране таймера, только по явному
    действию пользователя "запомнить как значение по умолчанию" (issue #59,
    волна 2). Ровно одно из duration_seconds/sound_volume_percent должно
    быть задано (см. _check_exactly_one_value ниже):

    - duration_seconds — одна из трёх длительностей, block_letter="A"/"B"
      выбирает отдых между подходами того блока, None — большой перерыв
      между блоками;
    - sound_volume_percent (issue #90) — громкость звука таймера, 0..100%,
      0 — валидное значение ("выключить звук"), не привязана к блоку
      (block_letter должен быть None)."""

    block_letter: str | None = Field(default=None, pattern="^[AB]$")
    duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    sound_volume_percent: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _check_exactly_one_value(self) -> "TimerPreferencesUpdateRequest":
        if (self.duration_seconds is None) == (self.sound_volume_percent is None):
            raise ValueError(
                "Ровно одно из duration_seconds/sound_volume_percent должно быть задано",
            )
        if self.sound_volume_percent is not None and self.block_letter is not None:
            raise ValueError("block_letter не используется вместе с sound_volume_percent")
        return self


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


class FreeWorkoutPlanResponse(BaseModel):
    """GET /api/free-workout/plan (issue #109) — тот же путь, что
    handle_free_workout_start бота (app/bot/handlers/free_workout.py):
    снаряд здесь ВСЕГДА явный выбор, как у бэкдейта (см. BackdateSubmitRequest),
    не наследуется молча из прогрессии — свободные подтягивания вне цикла
    программы, унаследовать target/work_sets/снаряд из resolve_next_targets
    здесь не от чего (эти числа для основной программы, свободный вход в
    неё не входит).

    Нет статуса "no_access" — свободные подтягивания не за паивеллом, ни в
    боте (handle_free_workout_start не проверяет подписку), ни здесь, тот
    же принцип, что у ElectivePlanResponse. "ready" — только workout_set_id
    (нужен для последующего submit) и band_items (личный список резин для
    выбора снаряда)."""

    status: str
    workout_set_id: int | None = None
    band_items: list[BandItemInfo] = Field(default_factory=list)


class FreeWorkoutSubmitRequest(BaseModel):
    """POST /api/free-workout/submit — произвольное число рабочих подходов
    (issue #109, тот же смысл, что свободный текстовый ввод бота через
    parse_reps: сколько реально сделал, столько и ввёл), не фиксированные
    3+1 обычного блока A. equipment_* — тот же смысл и та же серверная
    валидация, что у BackdateSubmitRequest (см. app/web/routes.py::
    _resolve_explicit_equipment) — снаряд не наследуется, указывается явно."""

    working_reps: list[Reps] = Field(min_length=1)
    max_reps: Reps
    equipment_type: str
    equipment_value: Decimal | None = Field(default=None, gt=0)
    equipment_item_id: int | None = None
    comment: str | None = None
    confirm_anomalies: bool = False


class FreeWorkoutSubmitResponse(BaseModel):
    status: str
    result_text: str | None = None
    equipment: EquipmentInfo | None = None
    anomalies: AnomalyFlagsResponse | None = None


class LeaderboardEntryResponse(BaseModel):
    """Одна строка лидерборда (issue #67) — display_name уже подставлен
    "Аноним" вместо NULL на уровне веб-роута (это форматирование, не
    доменное правило). value — Decimal вне зависимости от метрики (для
    max_reps/total_volume это целое число, сериализуется тем же способом,
    что и остальные Decimal-поля проекта)."""

    rank: int
    display_name: str
    value: Decimal
    is_current_user: bool


class LeaderboardResponse(BaseModel):
    """GET /api/leaderboard?metric=...&gender=...&age_bucket=... — entries
    содержит топ-N плюс, если он вне топа, отдельной строкой в конце — самого
    запрашивающего пользователя (is_current_user=True у ровно одной строки,
    либо ни у одной, если он не онбордился или не входит в выбранный
    фильтр). my_display_name — текущая настройка имени пользователя (для
    поля ввода на этом же экране), не зависит от entries."""

    metric: str
    entries: list[LeaderboardEntryResponse] = Field(default_factory=list)
    my_display_name: str | None = None
    my_rank: int | None = None


class LeaderboardDisplayNameUpdateRequest(BaseModel):
    """PUT /api/leaderboard/display-name — всегда перезаписывает целиком
    (в отличие от WorkoutSubmitRequest, где None у части полей значит
    "не трогать"). Пустая строка нормализуется в None на уровне роута —
    тот же результат, что и явный null, "анонимно"."""

    display_name: str | None = Field(default=None, max_length=64)


class LeaderboardDisplayNameResponse(BaseModel):
    display_name: str | None


class ElectiveTypeInfo(BaseModel):
    """Один доступный сейчас формат факультатива (issue #94) — та же
    ротация без повтора, что и app.domain.electives.available_elective_types
    использует для elective_type_keyboard бота, просто списком для
    фронтенда вместо inline-кнопок.

    input_kind различает вид формы: "sequence" — раскладка по подходам
    (min_count/max_count ограничивают длину списка — тот же смысл, что
    _SEQUENCE_LIMITS в app/bot/handlers/electives.py), "total" — одно
    число (только volume_target, min_count/max_count тогда None).
    volume_goal — тот же ×5 ориентир от текущей цели блока на объём, что
    показывает бот (app.domain.electives.volume_target_goal), заполнен
    только для volume_target."""

    value: str
    label: str
    input_kind: Literal["sequence", "total"]
    min_count: int | None = None
    max_count: int | None = None
    volume_goal: int | None = None


class ElectivePlanResponse(BaseModel):
    """GET /api/elective/plan (issue #94) — тот же путь, что
    handle_electives_start бота (app/bot/handlers/electives.py): доступность
    факультатива НЕ привязана к готовности к обычной тренировке (кнопка
    "🎯 Факультатив" в workout_section_keyboard бота видна в любой день) —
    is_rest_day здесь только для текста ("сегодня как раз день отдыха"), не
    гейт самой формы.

    status: "not_onboarded"/"needs_first_workout" — форма не показывается,
    тот же принцип, что и у остальных *PlanResponse (см. WorkoutPlanResponse).
    Нет статуса "no_access" — факультатив не за паивеллом, ни в боте
    (handle_electives_start не проверяет подписку), ни здесь. "ready" —
    остальные поля заполнены.

    elective_allowed=False — недельный лимит (elective_limit,
    entries_this_week) уже исчерпан — фронтенд обязан показать явный текст
    (issue #94, уточнение в комментарии: "не просто скрыть кнопку молча"),
    available_types в этом случае пуст (форма ввода не показывается)."""

    status: str
    is_rest_day: bool = False
    ready_at: str | None = None
    hours_left: int | None = None
    elective_allowed: bool = False
    elective_limit: int = 0
    entries_this_week: int = 0
    available_types: list[ElectiveTypeInfo] = Field(default_factory=list)
    equipment_label: str | None = None


class ElectiveSubmitRequest(BaseModel):
    """POST /api/elective/submit — тот же смысл полей, что финальный шаг
    бота (app/bot/handlers/electives.py::_finalize_elective): reps_sequence
    — раскладка по подходам для max_reps_ladder/w_ladder/three_minutes,
    None для volume_target (там только итог). total_reps обязателен
    всегда — для форматов с раскладкой сервер игнорирует присланную сумму
    и пересчитывает её сам из reps_sequence (не доверяем клиентской
    арифметике), для volume_target это единственное число.

    Длина reps_sequence проверяется на сервере против тех же min/max, что
    вернул GET /api/elective/plan (ElectiveTypeInfo.min_count/max_count) —
    тот же принцип, что и у остальных Submit-эндпойнтов (сервер не
    доверяет буквально ответу предыдущего GET, пересчитывает сам)."""

    elective_type: str
    reps_sequence: list[Reps] | None = None
    total_reps: Reps


class ElectiveSubmitResponse(BaseModel):
    status: str
    result_text: str | None = None
    equipment_label: str | None = None
