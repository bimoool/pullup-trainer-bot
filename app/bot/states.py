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

    # "➕ Добавить резину" из Профиля (Часть 10, п. 22) — заведение снаряда
    # заранее, вне очереди выбора для конкретного блока тренировки;
    # отдельные состояния, чтобы не путать с equipment_queue-флоу выше.
    waiting_for_standalone_item_name = State()
    waiting_for_standalone_item_kg = State()


class WorkoutStates(StatesGroup):
    waiting_for_block_a = State()
    # Уточнение по аномалии ввода (пакет #4) — распарсено успешно, но
    # detect_anomalies что-то заметило; ждём "Всё верно"/"Ввести заново"
    # прежде чем продолжать так, как будто ввод был чистым.
    waiting_for_block_a_confirm = State()
    waiting_for_block_b = State()
    waiting_for_block_b_confirm = State()
    waiting_for_comment = State()


class EditWorkoutStates(StatesGroup):
    waiting_for_block_a = State()
    waiting_for_block_a_confirm = State()
    waiting_for_block_b = State()
    waiting_for_block_b_confirm = State()
    # Правка веса/резины "в этом же отчёте" (Часть 10) — только для блоков
    # с корректируемым значением (WEIGHT/BAND), по очереди, с пропуском.
    waiting_for_equipment_weight = State()
    waiting_for_equipment_band = State()


class BackdateStates(StatesGroup):
    waiting_for_date = State()
    waiting_for_block_a = State()
    waiting_for_block_a_confirm = State()
    # Выбор формата ввода блока Б (issue #88) — по честной раскладке
    # подходов (waiting_for_block_b, как раньше) или только итог без неё
    # (waiting_for_block_b_total[_max], см. app/bot/handlers/backdate.py).
    waiting_for_block_b_mode = State()
    waiting_for_block_b = State()
    waiting_for_block_b_confirm = State()
    waiting_for_block_b_total = State()
    waiting_for_block_b_total_max = State()


class FreeWorkoutStates(StatesGroup):
    """"➕ Внести свободные подтягивания" (Часть 10, п. 18, пакет #2 п.21) —
    вне схемы, вне сета из 12, вне каскада. Снаряд + произвольное
    количество подходов, не фиксированная схема."""

    waiting_for_equipment_type = State()
    waiting_for_equipment_value = State()
    waiting_for_band_choice = State()
    waiting_for_new_item_name = State()
    waiting_for_new_item_kg = State()
    waiting_for_reps = State()
    waiting_for_reps_confirm = State()


class ElectiveStates(StatesGroup):
    """Факультативная нагрузка вне плана (пакет #6, app/domain/electives.py)
    — 4 формата, ротация без повтора + не чаще раза в неделю. Снаряд не
    спрашивается (всегда тот же, что в блоке на объём) — сразу выбор
    формата, потом ввод результата."""

    waiting_for_type = State()
    waiting_for_reps = State()  # последовательность — max_reps_ladder/w_ladder/three_minutes
    waiting_for_total = State()  # одно число — volume_target


class FeedbackStates(StatesGroup):
    waiting_for_text = State()


class AdminStates(StatesGroup):
    waiting_for_broadcast_text = State()
    waiting_for_dm_text = State()
    waiting_for_grant_days = State()
    waiting_for_grant_coins = State()
    # Выставляется не через колбэк, а программно из воркера
    # (app/workers/weekly_digest.py) в момент отправки еженедельного
    # напоминания — так следующее сообщение админа однозначно привязано
    # именно к этому напоминанию, не к случайному сообщению боту.
    waiting_for_weekly_digest_text = State()
