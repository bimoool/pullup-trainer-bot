from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    waiting_for_baseline_reps = State()
    waiting_for_band_thickness = State()
    waiting_for_weight = State()
    waiting_for_height = State()
    waiting_for_age = State()
    waiting_for_timezone = State()  # выбор кнопкой, но состояние нужно для game-over защиты от левого ввода


class NewBandStates(StatesGroup):
    """Отдельная короткая ветка: когда предыдущая тренировка сообщила
    equipment_changed=True для блока A, перед следующей тренировкой
    спрашиваем новую толщину резины (домен знает только ЧТО снаряд
    поменялся, не какой конкретно — см. Этап 1)."""

    waiting_for_band_thickness = State()


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
