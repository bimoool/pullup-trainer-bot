from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    waiting_for_baseline_reps = State()
    waiting_for_weight = State()
    waiting_for_height = State()
    waiting_for_age = State()
    waiting_for_timezone = State()  # выбор кнопкой, но состояние нужно для game-over защиты от левого ввода


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
    вводит сам, см. Часть 1)."""

    waiting_for_type = State()
    waiting_for_value = State()


class WorkoutStates(StatesGroup):
    waiting_for_block_a = State()
    waiting_for_block_b = State()
    waiting_for_comment = State()


class EditWorkoutStates(StatesGroup):
    waiting_for_block_a = State()
    waiting_for_block_b = State()


class BackdateStates(StatesGroup):
    waiting_for_date = State()
    waiting_for_block_a = State()
    waiting_for_block_b = State()


class AdminStates(StatesGroup):
    waiting_for_broadcast_text = State()
    waiting_for_dm_text = State()
    waiting_for_grant_days = State()
    waiting_for_grant_coins = State()
