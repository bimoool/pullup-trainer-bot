from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class EquipmentType(StrEnum):
    """Точка на единой шкале нагрузки: толстая резина → тонкая резина →
    собственный вес → отягощение. AUSTRALIAN — не про сопротивление в кг
    вообще (регулируется углом корпуса), поэтому вне числовой шкалы —
    to_signed_load() для неё не определена."""

    BAND = "band"
    BODYWEIGHT = "bodyweight"
    WEIGHT = "weight"
    AUSTRALIAN = "australian"


class VolumeGrowthReason(StrEnum):
    """Почему выросло число рабочих подходов блока на объём (issue #79) —
    объяснение пользователю ДО начала тренировки, откуда взялся лишний
    подход. Единственный источник причины: app.domain.progression.
    recalculate_volume_block (VolumeBlockResult.work_sets_growth_reason) —
    дальше по цепочке (BlockAssignment → Block → NextBlockState →
    бот/Mini App) только проброс и форматирование в текст, без повторного
    вычисления."""

    STALL = "stall"  # застой: несколько тренировок подряд без роста
    CEILING = "ceiling"  # упор в потолок повторений за подход


class ExerciseType(StrEnum):
    """Задел под будущее расширение (отжимания на брусьях, выходы силой,
    подтягивания на одной руке) — сейчас только подтягивания. Раньше жил в
    app/db/models.py — перенесено в домен по той же логике, что и
    EquipmentType: это словарь предметной области, а не деталь схемы."""

    PULL_UPS = "pull_ups"


def to_signed_load(equipment_type: EquipmentType, equipment_value: Decimal | None) -> Decimal:
    """Переводит снаряд в одну знаковую величину общей шкалы нагрузки.

    У резины и веса противоположный знак у "большего числа": толще резина
    (больше кг сопротивления) — легче тянуться, поэтому резина уходит в
    минус; больше отягощение — тяжелее, значит в плюс. Все сравнения
    "легче/тяжелее" и "прежний/следующий снаряд" должны идти только через
    эту функцию, а не напрямую через equipment_value — иначе направление
    легко перепутать местами.
    """
    if equipment_type == EquipmentType.BAND:
        return -abs(equipment_value or Decimal(0))
    if equipment_type == EquipmentType.BODYWEIGHT:
        return Decimal(0)
    if equipment_type == EquipmentType.WEIGHT:
        return abs(equipment_value or Decimal(0))
    raise ValueError(f"{equipment_type} не имеет знаковой величины на шкале нагрузки")


@dataclass(frozen=True)
class BlockConfig:
    """Параметры прогрессии одного блока. equipment здесь больше нет —
    снаряд не привязан к блоку жёстко, оба блока независимо двигаются по
    одной шкале (см. EquipmentType).

    max_step/coef убраны (пятая по счёту переработка формулы прогрессии) —
    шаг роста теперь процентный, единый для обоих блоков, см. STEP_PCT и
    app.domain.progression.recalculate_target. bodyweight_ceiling тоже убран:
    старый "потолок 25 без дальнейшего роста" для объёмного блока заменён
    новой системой (потолок VOLUME_TARGET_CEILING → доп. подходы до 8 →
    отягощение, см. recalculate_volume_block) — держать оба потолка
    параллельно означало бы конфликт условий."""

    base_target: int
    work_sets: int
    # ОБЪЁМНЫЙ блок: СТАРТОВОЕ число рабочих подходов — дальше растёт по
    # правилу застоя/потолка (recalculate_volume_block), до
    # VOLUME_WORK_SETS_CEILING. СИЛОВОЙ блок: фиксировано навсегда, как и
    # было.
    equipment_change_threshold: int
    # Снаряд меняется, когда КАЖДЫЙ рабочий подход факт достиг этого порога —
    # сравнение с сырыми повторениями, а не с расчётной новой целью. Для
    # объёмного блока это по-прежнему двигает BAND→BODYWEIGHT как раньше;
    # переход BODYWEIGHT→WEIGHT для него теперь идёт только через новую
    # систему (recalculate_volume_block подавляет здесь общий механизм на
    # этом этапе), не через этот порог.
    min_viable_reps: int
    # Максимум ниже этого на новом снаряде — снаряд подобран неверно.


VOLUME_BLOCK = BlockConfig(base_target=10, work_sets=3, equipment_change_threshold=20, min_viable_reps=10)
STRENGTH_BLOCK = BlockConfig(base_target=3, work_sets=4, equipment_change_threshold=7, min_viable_reps=3)

# Процентный шаг прогрессии (пятая переработка формулы) — 5% от текущей
# цели за подход (не от того, насколько перевыполнен максимум — осознанное
# решение: рост ограничен как доля ОТ ТЕКУЩЕЙ НАГРУЗКИ, а не от степени
# перевыполнения, см. источники по прогрессивной перегрузке в промпте).
# Тот же процент применяется к росту веса в объёмном блоке после перехода
# на отягощение (VOLUME_WEIGHT_MIN_STEP_KG). Округление вверх, минимум +1
# (иначе на малых числах рост останавливается).
STEP_PCT: float = 0.05

# --- Рост блока на объём сверх обычной формулы (потолок → подходы → вес) ----------
# Конкретные числа — продуктовое решение, не научный факт (зафиксировано по
# просьбе автора): потолок 33 повторений, до 8 рабочих подходов, дальше вес
# с 5 кг. Опирается на реальный принцип прогрессивной перегрузки (рост не
# более ~10%/неделю, гипертрофия/выносливость — объём вплоть до ~25
# повторений в подходе), но точные пороги ниже — выбор продукта, не цитата
# из источника. Было 30 (ревизия v5) — единая константа: тот же порог теперь
# ещё и точка старта блока на объём сразу с отягощением по замеру, см.
# suggest_starting_equipment ниже по коду (app/domain/progression.py) —
# сознательно одно число на оба сценария, не два разных.
VOLUME_TARGET_CEILING: int = 33
VOLUME_WORK_SETS_CEILING: int = 8
VOLUME_STALL_THRESHOLD: int = 4
# Столько подряд тренировок без роста цели (см.
# count_consecutive_stalled_workouts) добавляют +1 рабочий подход, если
# потолок подходов ещё не достигнут.
VOLUME_BIG_OVERSHOOT_THRESHOLD: int = 50
# Расчётная цель (до отката) ниже этого — откат до VOLUME_MODERATE_ROLLBACK_TARGET,
# +1 подход. Равна или выше — откат до потолка (VOLUME_TARGET_CEILING), подходов добавляется
# ceil(расчётная_цель / VOLUME_TARGET_CEILING) — распределяет объём на
# разумное число подходов вместо одного огромного.
VOLUME_MODERATE_ROLLBACK_TARGET: int = 20
VOLUME_WEIGHT_START_KG = Decimal(5)
VOLUME_WEIGHT_MIN_STEP_KG: float = 0.5

# --- Ежемесячная разгрузочная тренировка блока на объём ---------------------------
DELOAD_INTERVAL_DAYS: int = 30
DELOAD_REPS: int = 50

# Пороги стартового снаряда силового блока по замеру (Часть 10 — раньше
# suggest_starting_equipment ошибочно применял пороги объёмного блока к
# обоим блокам). Объёмный блок использует свой собственный порог —
# VOLUME_BLOCK.base_target, строго больше (не >=).
STRENGTH_START_WEIGHT_MIN_REPS: int = 8
STRENGTH_START_BODYWEIGHT_MIN_REPS: int = 3

# Отсрочка отката цели (Часть 10, пакет #2, п.13) — "слабая" тренировка
# (объём меньше предыдущего) откатывает цель на -1 только после стольких
# подряд слабых тренировок, не после первой же. Заменяет собой прежнее
# правило "объём везде, без отката" (NO_CAP_MAX_SPREAD удалён вместе с ним).
WEAK_STREAK_ROLLBACK_THRESHOLD: int = 3

WEIGHT_STEP_PCT: float = 0.125
WEIGHT_ROUND_TO_KG: float = 1.25
MIN_REST_DAYS: int = 2
SET_LENGTH: int = 12
BASELINE_VALID_DAYS: int = 35
GAP_ROLLBACK_DAYS: int = 21
GAP_RETEST_DAYS: int = 35
ROLLBACK_REPS: int = 2
ROLLBACK_WEIGHT_PCT: float = 0.10
TRIAL_DAYS: int = 14

# Продуктовая константа платной подписки (990₽/мес) — раньше жила в
# app/services/tribute.py (единственном на тот момент платёжном провайдере),
# перенесена сюда при удалении Tribute (отказ в верификации продавца):
# и Robokassa, и Stars (payments_stars.py) ссылаются на неё одинаково,
# провайдер-специфичного смысла в ней нет.
SUBSCRIPTION_PRICE_RUB: int = 990
SUBSCRIPTION_DAYS: int = 30
SUBSCRIPTION_DESCRIPTION: str = f"Доступ на {SUBSCRIPTION_DAYS} дней"

# Диагностический платёж для админа (app/bot/handlers/admin.py) — та же
# ссылка Robokassa, что и у обычной подписки, только на 1₽ вместо
# SUBSCRIPTION_PRICE_RUB: проверить весь путь (создание ссылки → реальная
# оплата → опрос OpStateExt воркером → продление подписки) вживую, не
# тратя 990₽ на каждую проверку.
ADMIN_TEST_PAYMENT_AMOUNT_RUB: int = 1

# Еженедельный дайджест новостей продукта (app/workers/weekly_digest.py +
# app/bot/handlers/admin.py) — сколько ждать ответа админа на напоминание,
# прежде чем молча пропустить неделю. Общий источник для воркера
# (сравнивает при отправке напоминания) и хендлера (сравнивает при получении
# ответа) — единственная причина держать константу в domain, а не в самом
# воркере: bot/handlers не должен зависеть от app.workers (обратное
# направление импорта не используется больше нигде в проекте).
WEEKLY_DIGEST_REPLY_DEADLINE_HOURS: int = 24

# --- Персистентные настройки длительности таймера Mini App (issue #59) -----------
# Дефолты для тех, кто ничего не настраивал (см. app.db.models.User::
# rest_seconds_block_a/rest_seconds_block_b/big_break_seconds) — ручное зеркало
# чисел, которые бот сообщает текстом в app.bot.texts.WORKOUT_PLAN
# ("Отдых между подходами — 4 минуты"/"3 минуты") и OPTIONAL_EXERCISE_OFFER
# ("Отдых 15 минут") — там это не enforced-константа, только текст. Продуктовое
# решение (объёмный блок восстанавливается дольше силового), не физический факт.
DEFAULT_REST_SECONDS_BLOCK_A: int = 240
DEFAULT_REST_SECONDS_BLOCK_B: int = 180
DEFAULT_BIG_BREAK_SECONDS: int = 900
# Громкость звука таймера (issue #90) — 0..100%, тот же принцип NULL-значит-
# дефолт, что у трёх настроек выше (см. app.db.models.User::sound_volume_percent).
# Максимум (100%), а не середина — жалоба в issue была именно "слишком тихо",
# не "нет вариантов": самый громкий вариант из доступных — разумный дефолт
# без произвольного выбора конкретного процента ниже потолка. "Громче
# текущего" достигается не только этим (100% > implicit-до-issue #90
# поведения без регулировки), но и подъёмом базовых peakGain в
# webapp-frontend/src/sound.ts — иначе даже 100% воспроизводило бы тот же
# тихий звук, что и раньше.
DEFAULT_TIMER_SOUND_VOLUME_PERCENT: int = 100

TRANSITION_RETRY_WORKOUTS: int = 4
# Тренировок на прежнем снаряде после неудачного перехода, прежде чем
# предлагать повторную попытку.

# --- Рекомендации (app/domain/recommendations.py) — типы 1 и 2 ------------------

UNDERWORKING_GAP_THRESHOLD: int = 5
# Максимум минус средние рабочие подходы >= этого — рабочие подходы идут
# сильно легче максимума, есть простор нагружать их больше.
EQUIPMENT_TOO_LIGHT_MARGIN: int = 5
EQUIPMENT_TOO_LIGHT_LOOKBACK: int = 3
# Максимум стабильно превышает цель на EQUIPMENT_TOO_LIGHT_MARGIN и больше
# на протяжении EQUIPMENT_TOO_LIGHT_LOOKBACK тренировок подряд на одном
# снаряде — снаряд явно недооценивает уровень.
WEAK_SET_DROP_THRESHOLD: int = 3
WEAK_SET_LOOKBACK: int = 3
# Конкретный по номеру рабочий подход в среднем ниже остальных подходов той
# же тренировки минимум на столько — за последние WEAK_SET_LOOKBACK тренировок.
VOLUME_DROP_LOOKBACK: int = 3
MINIMAL_REST_MARGIN_DAYS: int = 1
# Промежуток между тренировками не превышает MIN_REST_DAYS + этот запас —
# считается "на грани минимального отдыха".
CONSISTENT_STREAK_DAYS: int = 21

# --- Аномалии ввода (app/domain/anomalies.py) — пакет #4 --------------------------

ANOMALY_LARGE_VALUE_THRESHOLD: int = 50
# Любое число в подходе строго больше этого — повод переспросить, вне
# зависимости от истории. Ниже жёсткого предела ввода (parsing.MAX_REPS=100).
ANOMALY_JUMP_MULTIPLIER: float = 2.0
# Среднее рабочих подходов сейчас минимум во столько раз выше среднего
# прошлой тренировки этого же блока — повод переспросить. Именно среднее
# рабочих подходов (не объём и не максимум) — это та же метрика, на
# которой уже построена сама формула прогрессии (recalculate_target), и
# единственная из трёх, что остаётся сравнимой между тренировками с разным
# числом подходов (объём при большем числе подходов растёт тривиально).
