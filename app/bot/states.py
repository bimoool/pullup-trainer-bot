from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    waiting_for_baseline_reps = State()
    # Подтверждение введённого числа (Часть 10 — живое тестирование
    # показало, что опечатку в замере до этого нечем было поймать):
    # baseline не пишется в БД, пока не подтверждён.
    waiting_for_baseline_confirm = State()
    waiting_for_weight = State()
    waiting_for_height = State()
    waiting_for_gender = State()
    waiting_for_birth_date = State()
    waiting_for_timezone = State()  # свободный текст (город), см. app/bot/timezones.py


class ProfileEditStates(StatesGroup):
    """«✏️ Изменить профиль» — те же вопросы/валидация, что и в анкете, но
    по одному полю за раз (не пересобирать весь профиль ради одного
    изменившегося числа)."""

    waiting_for_weight = State()
    waiting_for_height = State()
    waiting_for_gender = State()
    waiting_for_birth_date = State()
    waiting_for_timezone = State()


class RetestStates(StatesGroup):
    """Замер устарел (>35 дней с последней тренировки, см.
    domain.rules.check_training_readiness/GAP_RETEST_REQUIRED) — просим
    только новое число, анкету заново НЕ переспрашиваем (профиль уже
    заполнен и не менялся)."""

    waiting_for_baseline_reps = State()


class EquipmentStates(StatesGroup):
    """Общий шаг выбора снаряда — используется и для самой первой
    тренировки (стартовый снаряд по итогам замера,
    domain.suggest_starting_equipment), и когда предыдущая тренировка
    сообщила equipment_changed=True для одного из блоков (домен знает
    только ЧТО снаряд надо менять, не какой конкретно — пользователь
    вводит сам, см. Часть 1), и для бэкдейта (Часть 8 — там снаряд теперь
    тоже спрашивается явно, а не тихо наследуется).

    waiting_for_band_choice/waiting_for_new_item_name/waiting_for_new_item_kg
    — подшаги личного списка резин (Часть 8): выбор уже добавленного
    снаряда или создание нового именованного пункта."""

    waiting_for_type = State()
    waiting_for_value = State()
    waiting_for_band_choice = State()
    waiting_for_new_item_name = State()
    waiting_for_new_item_kg = State()


class WorkoutStates(StatesGroup):
    waiting_for_block_a = State()
    waiting_for_block_b = State()
    waiting_for_comment = State()


class EditWorkoutStates(StatesGroup):
    waiting_for_block_a = State()
    waiting_for_block_b = State()
    # Правка веса/резины "в этом же отчёте" (Часть 10) — только для блоков
    # с корректируемым значением (WEIGHT/BAND), по очереди, с пропуском.
    waiting_for_equipment_weight = State()
    waiting_for_equipment_band = State()


class BackdateStates(StatesGroup):
    waiting_for_date = State()
    waiting_for_block_a = State()
    waiting_for_block_b = State()


class FeedbackStates(StatesGroup):
    waiting_for_text = State()


class AdminStates(StatesGroup):
    waiting_for_broadcast_text = State()
    waiting_for_dm_text = State()
    waiting_for_grant_days = State()
    waiting_for_grant_coins = State()
