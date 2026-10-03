"""Сидирование фиксированных пользователей для Playwright E2E-набора Mini
App (issue #126, webapp-frontend/e2e/) — по одному вызову на сценарий
перед стартом Playwright, тем же кодом (repositories/services), что уже
используют tests/test_web/*.py (см. _make_returning_user в
tests/test_web/test_workout.py — сценарий "ready" здесь дословно
повторяет тот же рецепт), не отдельный сервисный слой заново: E2E не
должен рассинхронизироваться с реальной формой данных в БД.

Первая итерация — только 3 сценария, согласованные в issue (остальные
пять — отдельными issue после того, как инфраструктура обкатана):
  - not_onboarded — ничего не сидирует, статус берётся из отсутствия строки
    users (см. app/web/routes.py::get_hello/get_workout_plan).
  - first_workout — анкета полностью пройдена, ни одной тренировки ещё не
    было.
  - ready — одна прошлая тренировка 5 дней назад, обычный день тренировки.

Обновление (issue #126, разбор повторного падения CI после мержа issue
#124 PR 2): оба сценария с сидированием раньше вызывали
SubscriptionService.start_trial напрямую и не отмечали
user.onboarding_completed_at вообще — до PR 2 issue #124 это было
достаточно (HelloResponse.is_onboarded значило просто "строка users
существует"). Теперь GET /api/hello (onboarding_step) проверяет
onboarding_completed_at ПЕРВЫМ, раньше истории тренировок — с
onboarding_completed_at=None App.tsx рендерит OnboardingScreen вместо
WorkoutScreen вообще, независимо от того, есть ли уже тренировки в
истории. Оба сценария теперь проходят через OnboardingService целиком
(record_baseline_and_start + complete_questionnaire_and_start_trial — тот
же путь, что и настоящий онбординг, start_trial внутри неё же, отдельный
вызов SubscriptionService.start_trial убран, чтобы не стартовать триал
дважды).

Использование (тот же DATABASE_URL/BOT_TOKEN, что у app/web/main.py):
    python scripts/e2e_seed.py ready 900003

Волна 5 (issue #185, экран сессии) добавляет три сценария многокурсовой
схемы (app/db/models_program.py) поверх admin-only вкладки "Dashboard" (v2,
SessionV2Lab.tsx) — тот же приём "не отдельный сервисный слой", что и
сценарии выше, только сервисы/репозитории уже другие (ProgramInclusionService/
TrainingSessionLogService волны 3, не WorkoutRepository старой схемы):
  - v2_session_ready — STEP-курс, block_a work_sets=3 (итого 3+1=4 подхода
    на сессию) — под E2E "офлайн 4 подхода" раздела 15.
  - v2_session_complex — Program без стратегии + Complex из 3 упражнений,
    один PlanItem — под E2E "комплекс из 3, сделал 2".
  - v2_session_progression_edit — STEP-курс с ОДНОЙ прошлой сессией вчера,
    числа блока A/Б те же, что tests/test_web/test_v2_live_session.py::
    test_complete_live_session_applies_step_progression_matching_direct_strategy_call
    (не выдуманы заново) — под E2E "правка вчерашней сессии".

ВАЖНО: эти сценарии видны только тестировщикам из ADMIN_IDS
(app.config.settings.is_admin, см. App.tsx::DASHBOARD_V2_NAV_TAB) — CI
должен добавить telegram_id сценария в ADMIN_IDS отдельным шагом workflow
(агент, готовивший эту волну, не может редактировать .github/workflows/*,
см. PR-описание issue #185).

issue #193 (WORKER B, "Планы" → реальные PlanWeek) добавляет
plan_week_ready — НЕ admin-only (вкладка "Планы"/DashboardScreen.tsx видна
всем пользователям, не только ADMIN_IDS, в отличие от сценариев волны 5
выше). RECURRING-курс с одним PlanItem на день недели и одним в свободном
пуле — ни один из v2_session_* сценариев такого не даёт (все их PlanItem
day_of_week=NULL, они сделаны под экран сессии, не под "Планы"). CI должен
добавить отдельный шаг `python scripts/e2e_seed.py plan_week_ready
<telegram_id>` (тот же класс ограничения, что и ADMIN_IDS выше — агент не
может редактировать .github/workflows/e2e.yml)."""

import argparse
import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base, async_session_factory
from app.db.models import BodyMetric, Gender, User
from app.db.models_program import (
    AssessmentProtocol,
    AssessmentResult,
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    Program,
    ProgramItem,
    ProgressionStrategyProfile,
    SessionBlock,
    SessionPlanItem,
    SessionStatus,
    SetLog,
    SetTarget,
    TrainingPlan,
    TrainingSession,
    UserFavorite,
)
from app.db.repositories.body_metrics import BodyMetricRepository
from app.db.repositories.collections import CollectionRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import (
    SessionBlockInput,
    SetLogInput,
    TrainingSessionRepository,
)
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.multi_program import (
    MetricType,
    ProgramStructureType,
    SessionSource,
    WeekPhase,
    plan_week_number,
    plan_week_start_date,
)
from app.domain.progression_strategy import ProgressionStrategyType
from app.domain.session import BlockLog
from app.services.onboarding import OnboardingService
from app.services.program_inclusion import ProgramInclusionRequest, ProgramInclusionService
from app.services.session_log import TrainingSessionLogService
from scripts.seed_exercise_library import seed_exercise_library

BAND_VALUE = Decimal("15.0")

# Реальная демография значения не имеет для этих сценариев — заполняется
# только потому, что OnboardingService.complete_questionnaire_and_start_trial
# (issue #124) требует эти поля, чтобы отметить онбординг завершённым; без
# этого GET /api/hello никогда не вернёт onboarding_step="done", и App.tsx
# не покажет WorkoutScreen вообще.
_QUESTIONNAIRE_DEFAULTS = {
    "weight_kg": Decimal(75),
    "height_cm": 180,
    "gender": Gender.MALE,
    "birth_date": date(1995, 1, 1),
    "timezone": "Europe/Moscow",
}


async def seed_not_onboarded(session: AsyncSession, telegram_id: int) -> None:
    """Нарочно пустая функция — "не онбордился" означает отсутствие строки
    users вообще (см. app/web/routes.py::get_hello), не отдельное
    состояние, которое нужно создавать."""


async def seed_first_workout(session: AsyncSession, telegram_id: int) -> None:
    """Замер на 6 повторений — suggest_starting_equipment(6) даёт (BAND,
    BODYWEIGHT): блок A на резине, блок Б на собственном весе. Раньше здесь
    было 12 (даёт (BODYWEIGHT, WEIGHT)), специально ЧТОБЫ избежать резины —
    заведение резины в Mini App (issue #124, PR 3, BandItemSelect) тогда
    ещё не было сделано. Оно есть с PR 3 — теперь сценарий сознательно
    выбирает резину для одного из блоков, чтобы E2E реально проверял новый
    экран подтверждения стартового снаряда (issue #175,
    EquipmentPlanScreen.tsx) на случае, где снаряд нужно заранее подготовить
    (заведение резины через "+ Завести новую резину"), а не только на случае
    "снаряд не нужен". Анкета пройдена полностью (см. модульный докстрин
    выше), ни одной тренировки ещё не было — GET /api/workout/plan отдаёт
    status="ready" с is_first_workout=True."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="e2e")
    now = datetime.now(UTC)
    onboarding = OnboardingService(session)
    await onboarding.record_baseline_and_start(user_id=user.id, performed_at=now, reps=6)
    await onboarding.complete_questionnaire_and_start_trial(
        user_id=user.id, now=now, **_QUESTIONNAIRE_DEFAULTS,
    )
    # Курс в каталоге "Главной" — единственный путь начать первую тренировку
    # (глобальный старт убран, Checkpoint 5A): "Добавить в план" -> карточка
    # в "Планах" -> "Начать". Тот же STEP-курс, что у v2_session_ready, но
    # БЕЗ инклюзии — пользователь включает его сам.
    # Курс глобальный (каталог общий для всех), а не строки пользователя —
    # find-or-create по category, чтобы повторный сид не плодил дубли в
    # каталоге "Главной" (клик по названию был бы неоднозначным).
    category = "e2e_first_workout"
    program = (await session.execute(select(Program).where(Program.category == category))).scalars().first()
    if program is None:
        profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
        session.add(profile)
        await session.flush()
        program = Program(
            name="Первая тренировка", goal="e2e", structure_type=ProgramStructureType.RECURRING,
            category=category, progression_strategy_id=profile.id,
            config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
        )
        session.add(program)
        await session.flush()
        block_a = Exercise(name="Блок A", metric_type=MetricType.REPS, category=category, subcategory="block_a")
        block_b = Exercise(name="Блок Б", metric_type=MetricType.REPS, category=category, subcategory="block_b")
        session.add_all([block_a, block_b])
        await session.flush()
        session.add_all([
            ProgramItem(
                program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id,
                count_per_week=3, day_of_week=None,
            )
            for exercise in (block_a, block_b)
        ])
        await session.flush()


async def seed_ready(session: AsyncSession, telegram_id: int) -> None:
    """Один пользователь с ровно одной прошлой тренировкой 5 дней назад —
    снаряд (BAND, значение ниже порога смены обоих блоков) уже известен для
    обоих блоков, needs_new_equipment=False на следующей (см.
    app/db/repositories/workouts.py::_resolve_next_state) — GET
    /api/workout/plan отдаёт status="ready" с work_sets_a=3/work_sets_b=4,
    подтверждено tests/test_web/test_workout.py::
    test_plan_ready_shows_target_and_equipment.

    Заводит реальный EquipmentItem и передаёт его id в record_workout для
    обоих блоков (issue #173) — без этого equipment_a/b.item_id в ответе
    GET /api/workout/plan оставался бы null, а WorkoutScreen.tsx::handleSubmit
    (issue #148, "нечего унаследовать") молча блокировал бы отправку формы,
    требуя выбор/заведение резины, которого сценарий ready.spec.ts не делает
    — ровно так падал реальный прогон Playwright в CI (см. issue #173)."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="e2e")
    now = datetime.now(UTC)
    onboarding = OnboardingService(session)
    _baseline, workout_set, _user = await onboarding.record_baseline_and_start(
        user_id=user.id, performed_at=now, reps=10,
    )
    await onboarding.complete_questionnaire_and_start_trial(
        user_id=user.id, now=now, **_QUESTIONNAIRE_DEFAULTS,
    )
    band_item = await EquipmentItemRepository(session).create(
        user_id=user.id, name="Резина 15кг", resistance_kg=BAND_VALUE,
    )

    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        block_a_equipment_item_id=band_item.id, block_b_equipment_item_id=band_item.id,
    )


async def _onboard(session: AsyncSession, telegram_id: int) -> User:
    """Общий для трёх v2-сценариев ниже шаг "пользователь прошёл онбординг"
    — тот же рецепт, что seed_first_workout, вынесенный в helper, потому что
    сами v2-сценарии сидируют разные вещи ПОСЛЕ этого шага (STEP-курс/
    комплекс/история), не другой онбординг."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="e2e")
    now = datetime.now(UTC)
    onboarding = OnboardingService(session)
    await onboarding.record_baseline_and_start(user_id=user.id, performed_at=now, reps=12)
    await onboarding.complete_questionnaire_and_start_trial(user_id=user.id, now=now, **_QUESTIONNAIRE_DEFAULTS)
    return user


async def seed_v2_session_ready(session: AsyncSession, telegram_id: int) -> None:
    """STEP-курс синтетической категории — тот же рецепт, что
    tests/test_web/test_v2_live_session.py::_setup_step_session (PlanItem на
    каждую роль заводится напрямую, без ProgramItem: программа синтетическая,
    без недельной матрицы). work_sets=3 у блока A + дефолтный 1 подход блока
    Б (см. app.services.live_session._resolve_step_role_block) — сессия из
    ОБОИХ PlanItem даёт ровно 4 подхода, под E2E "офлайн, 4 подхода"."""
    user = await _onboard(session, telegram_id)

    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="E2E Live Session", goal="e2e", structure_type=ProgramStructureType.RECURRING,
        category="e2e_live_session", progression_strategy_id=profile.id,
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
    )
    session.add(program)
    await session.flush()
    session.add_all([
        Exercise(name="Блок A", metric_type=MetricType.REPS, category="e2e_live_session", subcategory="block_a"),
        Exercise(name="Блок Б", metric_type=MetricType.REPS, category="e2e_live_session", subcategory="block_b"),
    ])
    await session.flush()

    inclusion = await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )
    role_by_exercise_id = {e["exercise_id"]: e["role"] for e in inclusion.snapshot["exercises"]}

    plans = TrainingPlanRepository(session)
    plan = await plans.get_for_user(user.id)
    for exercise_id in role_by_exercise_id:
        session.add(
            PlanItem(
                training_plan_id=plan.id, exercise_id=exercise_id, count_per_week=3,
                program_inclusion_id=inclusion.id,
            ),
        )
    await session.flush()


async def seed_v2_session_complex(session: AsyncSession, telegram_id: int) -> None:
    """Комплекс из 3 упражнений (order_index 0..2, 1 подход каждое — под
    E2E "сделал 2 из 3, завершил") — Program БЕЗ стратегии прогрессии:
    ComplexItem/_resolve_complex_blocks не зависит от неё вовсе (см.
    app.services.live_session._resolve_complex_blocks)."""
    user = await _onboard(session, telegram_id)

    program = Program(
        name="E2E Complex", goal="e2e", structure_type=ProgramStructureType.SINGLE_LESSON,
        category="e2e_complex", config={},
    )
    session.add(program)
    complex_ = Complex(name="Комплекс на 3")
    session.add(complex_)
    await session.flush()

    exercises = [
        Exercise(name=f"Комплекс, упражнение {i + 1}", metric_type=MetricType.REPS, category="e2e_complex")
        for i in range(3)
    ]
    session.add_all(exercises)
    await session.flush()
    for order_index, exercise in enumerate(exercises):
        session.add(
            ComplexItem(
                complex_id=complex_.id, exercise_id=exercise.id, order_index=order_index,
                sets=1, target_value=Decimal(10), target_unit="reps",
            ),
        )
    await session.flush()

    # Комплекс должен быть в ТЕКУЩЕЙ неделе плана — вкладка "Планы" показывает
    # только элементы с plan_week_id (иначе "ничего не запланировано").
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    week_number = plan_week_number(plan.created_at.date(), datetime.now(UTC).date())
    week = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=week_number,
        start_date=plan_week_start_date(plan.created_at.date(), week_number), phase=WeekPhase.BASE,
    )
    session.add(PlanItem(
        training_plan_id=plan.id, exercise_id=exercises[0].id, complex_id=complex_.id, count_per_week=1,
        plan_week_id=week.id,
    ))
    await session.flush()


async def seed_v2_session_progression_edit(session: AsyncSession, telegram_id: int) -> None:
    """STEP-курс + ОДНА прошлая сессия вчера — числа те же, что уже
    доказаны в tests/test_web/test_v2_live_session.py::
    test_complete_live_session_applies_step_progression_matching_direct_strategy_call
    (11/11/11 блок A, 4/4/4/4 блок Б), не выдуманы заново под E2E. Правка
    E2E-сценария поднимает блок A до 16/16/16/18(max) — та же сильная
    правка, что tests/test_web/test_v2_progression_cascade.py::
    test_preview_and_apply_cascade_recomputes_full_chain_and_converges,
    гарантированно сдвигающая цель (deltas не пустой)."""
    user = await _onboard(session, telegram_id)

    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="E2E Progression Edit", goal="e2e", structure_type=ProgramStructureType.RECURRING,
        category="e2e_progression_edit", progression_strategy_id=profile.id,
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
    )
    session.add(program)
    await session.flush()
    session.add_all([
        Exercise(name="Блок A", metric_type=MetricType.REPS, category="e2e_progression_edit", subcategory="block_a"),
        Exercise(name="Блок Б", metric_type=MetricType.REPS, category="e2e_progression_edit", subcategory="block_b"),
    ])
    await session.flush()

    inclusion = await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )
    role_to_exercise_id = {e["role"]: e["exercise_id"] for e in inclusion.snapshot["exercises"]}

    def _sets(exercise_id: int, working: list[int], max_value: int) -> SessionBlockInput:
        sets = [
            SetLogInput(set_number=i + 1, metric_type=MetricType.REPS, value=Decimal(r), unit="reps")
            for i, r in enumerate(working)
        ]
        sets.append(
            SetLogInput(
                set_number=len(working) + 1, metric_type=MetricType.REPS, value=Decimal(max_value),
                unit="reps", is_max_set=True,
            ),
        )
        return SessionBlockInput(exercise_id=exercise_id, sets=sets)

    await TrainingSessionLogService(session).record_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=datetime.now(UTC) - timedelta(days=1),
        effort=None, comment=None, program_inclusion_id=inclusion.id,
        blocks=[
            _sets(role_to_exercise_id["block_a"], [11, 11, 11], 12),
            _sets(role_to_exercise_id["block_b"], [4, 4, 4, 4], 4),
        ],
    )


async def seed_plan_week_ready(session: AsyncSession, telegram_id: int) -> None:
    """issue #193 (WORKER B) — RECURRING-курс с ДВУМЯ ProgramItem: один
    закреплён за днём недели (day_of_week=1, вторник — см. соглашение
    DashboardScreen.tsx::DAY_NAMES), второй — свободный пул (day_of_week=
    NULL), тот же вид, что реальный сид "Подтягивания"
    (scripts/backfill_multi_program.py). Ни один из трёх уже существующих
    v2_session_* сценариев не даёт day_of_week-строку — они устроены под
    экран сессии (issue #185, "не трогать"), не под "Планы" — поэтому нужен
    отдельный сценарий, не переиспользование существующего telegram_id.

    Программа НАМЕРЕННО без ProgressionStrategyProfile (как
    _make_recurring_program в tests/test_services/test_plan_week_service.py)
    — "Планы" (DashboardScreen.tsx) в этом issue показывает только состав
    недели, не прогрессию/цели.

    GET /api/v2/plan сам материализует текущую PlanWeek и привязывает эти
    PlanItem к ней (ensure_current_plan_week, issue #188) — сидирование
    здесь останавливается на создании инклюзии, тот же принцип, что и у
    остальных v2_session_* сценариев выше (ничего не вызывает
    PlanWeekService заранее, это ответственность самого GET-эндпоинта)."""
    user = await _onboard(session, telegram_id)

    program = Program(
        name="Расписание недели (E2E)", goal="e2e", structure_type=ProgramStructureType.RECURRING,
        category="e2e_plan_week", config={},
    )
    session.add(program)
    await session.flush()

    exercise_day = Exercise(name="По вторникам", metric_type=MetricType.REPS, category="e2e_plan_week")
    exercise_pool = Exercise(name="Свободная тренировка", metric_type=MetricType.REPS, category="e2e_plan_week")
    session.add_all([exercise_day, exercise_pool])
    await session.flush()

    session.add_all([
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise_day.id,
            count_per_week=1, day_of_week=1,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise_pool.id,
            count_per_week=3, day_of_week=None,
        ),
    ])
    await session.flush()

    await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )


async def seed_plan_week_grouping(session: AsyncSession, telegram_id: int) -> None:
    """Integration fix (issue #188, checkpoint 2 review) — прямой воспроизводящий
    сценарий бага Worker B: RECURRING-курс с ДВУМЯ ProgramItem, оба
    day_of_week=NULL, одна ProgramInclusion — ровно форма реального сида
    "Подтягивания" (scripts/backfill_multi_program.py::seed_catalog).
    Без group-фикса это две отдельные строки ("Блок A"/"Блок Б"); с фиксом —
    одна карточка с program_name инклюзии.

    Отдельно — один ручной PlanItem (program_inclusion_id=NULL, тот же
    day_of_week=NULL, что у пары выше) — должен остаться своей отдельной
    карточкой, не слипнуться ни с группой, ни с потенциальным вторым ручным
    PlanItem."""
    user = await _onboard(session, telegram_id)

    program = Program(
        name="Подтягивания (E2E group)", goal="e2e", structure_type=ProgramStructureType.RECURRING,
        category="e2e_plan_week_group", config={},
    )
    session.add(program)
    await session.flush()

    block_a = Exercise(name="Блок A", metric_type=MetricType.REPS, category="e2e_plan_week_group")
    block_b = Exercise(name="Блок Б", metric_type=MetricType.REPS, category="e2e_plan_week_group")
    manual_exercise = Exercise(name="Растяжка", metric_type=MetricType.TIME, category="e2e_plan_week_group")
    session.add_all([block_a, block_b, manual_exercise])
    await session.flush()

    session.add_all([
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_a.id,
            count_per_week=3, day_of_week=None,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_b.id,
            count_per_week=3, day_of_week=None,
        ),
    ])
    await session.flush()

    await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )

    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    if plan is not None:
        # Ручной PlanItem, как его создаёт picker, всегда принадлежит PlanWeek: без plan_week_id
        # «Планы» не показывают его в недельном списке. Неделя — та же, что материализует GET /plan.
        today = datetime.now(UTC).date()
        week_number = plan_week_number(plan.created_at.date(), today)
        plans_repo = TrainingPlanRepository(session)
        week = await plans_repo.get_plan_week(training_plan_id=plan.id, week_number=week_number)
        if week is None:
            week = await plans_repo.create_plan_week(
                training_plan_id=plan.id, week_number=week_number,
                start_date=plan_week_start_date(plan.created_at.date(), week_number), phase=WeekPhase.BASE,
            )
        session.add(
            PlanItem(
                training_plan_id=plan.id, exercise_id=manual_exercise.id,
                count_per_week=2, day_of_week=None, program_inclusion_id=None, plan_week_id=week.id,
            ),
        )
        await session.flush()


async def seed_plan_week_add_exercise(session: AsyncSession, telegram_id: int) -> None:
    """Checkpoint 3 (issue #188) — Golden Journey "Планы -> Добавить
    упражнение": активная RECURRING-инклюзия «Подтягивания» (2 блока,
    day_of_week=NULL — тот же вид, что реальный сид) + засеянная Exercise
    Library (Планка/Отжимания, scripts/seed_exercise_library.py). Первый
    GET /api/v2/plan материализует текущую PlanWeek сам (ensure_current_
    plan_week вызывается из самого роута, issue #188 checkpoint 1) —
    здесь этого не делаем, только готовим исходные данные.

    Не переиспользует seed_plan_week_grouping (900014) намеренно — там уже
    есть свой ручной PlanItem "Растяжка" в свободном пуле, который сбивал
    бы точные assert'ы этого сценария (ожидается только "Подтягивания" в
    свободном пуле до добавления Планки/Отжиманий)."""
    user = await _onboard(session, telegram_id)
    await seed_exercise_library(session)

    program = Program(
        name="Подтягивания", goal="e2e", structure_type=ProgramStructureType.RECURRING,
        category="e2e_add_exercise", config={},
    )
    session.add(program)
    await session.flush()

    block_a = Exercise(name="Блок A", metric_type=MetricType.REPS, category="e2e_add_exercise")
    block_b = Exercise(name="Блок Б", metric_type=MetricType.REPS, category="e2e_add_exercise")
    session.add_all([block_a, block_b])
    await session.flush()

    session.add_all([
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_a.id,
            count_per_week=3, day_of_week=None,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_b.id,
            count_per_week=3, day_of_week=None,
        ),
    ])
    await session.flush()

    await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )


async def seed_plan_week_start_session(session: AsyncSession, telegram_id: int) -> None:
    """Checkpoint 4A (issue #188) — реальная STEP-программа "Подтягивания",
    материализованная через настоящий create_inclusion (ProgramItem +
    PlanWeek, не напрямую PlanItem, как в seed_v2_session_ready — той
    нужна была только готовая сессия, этой нужна ещё и реальная недельная
    карточка на "Планах", откуда стартует Golden Journey).

    Свежая инклюзия, ни одной TrainingSession в истории — readiness
    (app/web/routes_v2_dashboard.py::get_dashboard_status) проверяет
    too_early только если есть last_sessions, у новой инклюзии их нет —
    "ready" гарантирован без манипуляции датами."""
    user = await _onboard(session, telegram_id)

    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()

    program = Program(
        name="Подтягивания", goal="e2e", structure_type=ProgramStructureType.RECURRING,
        category="e2e_start_session", progression_strategy_id=profile.id,
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
    )
    session.add(program)
    await session.flush()

    block_a = Exercise(
        name="Блок A", metric_type=MetricType.REPS, category="e2e_start_session", subcategory="block_a",
    )
    block_b = Exercise(
        name="Блок Б", metric_type=MetricType.REPS, category="e2e_start_session", subcategory="block_b",
    )
    session.add_all([block_a, block_b])
    await session.flush()

    session.add_all([
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_a.id,
            count_per_week=3, day_of_week=None,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_b.id,
            count_per_week=3, day_of_week=None,
        ),
    ])
    await session.flush()

    await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )


async def seed_plan_week_manual_session(session: AsyncSession, telegram_id: int) -> None:
    """Checkpoint 4B (issue #188) — две manual PlanItem уже размещены по
    дням в текущей неделе (program_inclusion_id=NULL, ровно как их создаёт
    picker из Checkpoint 3), готовые к прямому клику "Начать": Планка
    (metric_type=time) — среда, Отжимания (metric_type=reps) — пятница.

    Никакой Program/ProgramInclusion не заводится вообще — manual-flow не
    должен от них зависеть (issue #188, ключевой пункт 6). PlanWeek
    материализуется тем же доменным расчётом, что и настоящий
    ensure_current_plan_week (app/domain/multi_program.py::plan_week_number/
    plan_week_start_date), не собственной датой наугад."""
    user = await _onboard(session, telegram_id)
    await seed_exercise_library(session)

    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()

    today = datetime.now(UTC).date()
    week_number = plan_week_number(plan.created_at.date(), today)
    week_start = plan_week_start_date(plan.created_at.date(), week_number)
    week = await TrainingPlanRepository(session).create_plan_week(
        training_plan_id=plan.id, week_number=week_number, start_date=week_start, phase=WeekPhase.BASE,
    )

    plank = (await session.execute(select(Exercise).where(Exercise.name == "Планка", Exercise.owner_user_id.is_(None)))).scalar_one()
    pushups = (await session.execute(select(Exercise).where(Exercise.name == "Отжимания", Exercise.owner_user_id.is_(None)))).scalar_one()

    session.add_all([
        PlanItem(
            training_plan_id=plan.id, exercise_id=plank.id, count_per_week=1,
            day_of_week=2, program_inclusion_id=None, plan_week_id=week.id,
        ),
        PlanItem(
            training_plan_id=plan.id, exercise_id=pushups.id, count_per_week=1,
            day_of_week=4, program_inclusion_id=None, plan_week_id=week.id,
        ),
    ])
    await session.flush()


async def seed_plan_week_stepper(session: AsyncSession, telegram_id: int) -> None:
    """issue #258 — две недели плана (прошлая и текущая), manual PlanItem'ы со
    счётчиками: текущая — «Планка» 2×/нед (1 завершённая сессия → 1/2) и
    «Отжимания» 1×/нед (0/1); прошлая — «Планка» 1×/нед (1/1). Сессии
    заведены напрямую (COMPLETED + SessionPlanItem), сам тест только читает."""
    user = await _onboard(session, telegram_id)
    await seed_exercise_library(session)

    now = datetime.now(UTC)
    plan = TrainingPlan(user_id=user.id, created_at=now - timedelta(days=14))
    session.add(plan)
    await session.flush()

    created = plan.created_at.date()
    current_number = plan_week_number(created, now.date())
    plans = TrainingPlanRepository(session)
    previous = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=current_number - 1,
        start_date=plan_week_start_date(created, current_number - 1), phase=WeekPhase.BASE,
    )
    current = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=current_number,
        start_date=plan_week_start_date(created, current_number), phase=WeekPhase.BASE,
    )

    async def exercise(name: str) -> Exercise:
        return (await session.execute(
            select(Exercise).where(Exercise.name == name, Exercise.owner_user_id.is_(None)),
        )).scalar_one()

    plank, pushups = await exercise("Планка"), await exercise("Отжимания")
    item_plank = PlanItem(
        training_plan_id=plan.id, exercise_id=plank.id, count_per_week=2, day_of_week=2, plan_week_id=current.id,
    )
    item_pushups = PlanItem(
        training_plan_id=plan.id, exercise_id=pushups.id, count_per_week=1, day_of_week=4, plan_week_id=current.id,
    )
    item_prev = PlanItem(
        training_plan_id=plan.id, exercise_id=plank.id, count_per_week=1, day_of_week=1, plan_week_id=previous.id,
    )
    session.add_all([item_plank, item_pushups, item_prev])
    await session.flush()

    def noon(week) -> datetime:
        return datetime.combine(week.start_date, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)

    for item, week in ((item_plank, current), (item_prev, previous)):
        training_session = TrainingSession(
            user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED, performed_at=noon(week),
        )
        session.add(training_session)
        await session.flush()
        session.add(SessionPlanItem(session_id=training_session.id, plan_item_id=item.id))
    await session.flush()


async def seed_plans_overview(session: AsyncSession, telegram_id: int) -> None:
    """issue #266 — обзор плана. Глобальные программы (find-or-create по имени):
    «Обзор: курс» (config.duration_weeks=8, вторник + свободный пул + пик),
    «Обзор: на удаление» (1 строка), «Обзор: прошлый» (подключён и уже убран) и
    «Обзор: превью» (не в плане, есть строки) / «Обзор: без расписания» (строк нет).
    Пользователю подключены первые три (прошлый — завершён вчера)."""
    user = await _onboard(session, telegram_id)
    await seed_exercise_library(session)

    async def exercise(name: str) -> Exercise:
        return (await session.execute(
            select(Exercise).where(Exercise.name == name, Exercise.owner_user_id.is_(None)),
        )).scalar_one()

    plank, pushups = await exercise("Планка"), await exercise("Отжимания")

    async def program(name: str, config: dict, items: list[tuple[Exercise, WeekPhase, int | None, int]]) -> Program:
        existing = (await session.execute(select(Program).where(Program.name == name))).scalars().first()
        if existing is not None:
            return existing
        created = Program(
            name=name, goal=f"цель: {name}", structure_type=ProgramStructureType.RECURRING,
            category="e2e_plans_overview", config=config,
        )
        session.add(created)
        await session.flush()
        for ex, phase, day, count in items:
            session.add(ProgramItem(
                program_id=created.id, week_phase=phase, exercise_id=ex.id, count_per_week=count, day_of_week=day,
            ))
        await session.flush()
        return created

    course = await program("Обзор: курс", {"duration_weeks": 8}, [
        (pushups, WeekPhase.BASE, 1, 2), (plank, WeekPhase.BASE, None, 3), (plank, WeekPhase.PEAK, 4, 1),
    ])
    removable = await program("Обзор: на удаление", {}, [(plank, WeekPhase.BASE, None, 1)])
    past = await program("Обзор: прошлый", {}, [(pushups, WeekPhase.BASE, None, 1)])
    await program("Обзор: превью", {"duration_weeks": 4}, [
        (pushups, WeekPhase.BASE, 0, 2), (plank, WeekPhase.BASE, 3, 1), (plank, WeekPhase.PEAK, None, 2),
    ])
    await program("Обзор: без расписания", {}, [])

    service = ProgramInclusionService(session)
    for target in (course, removable):
        await service.create_inclusion(user_id=user.id, request=ProgramInclusionRequest(program_id=target.id))
    ended = await service.create_inclusion(user_id=user.id, request=ProgramInclusionRequest(program_id=past.id))
    ended.is_active = False
    ended.started_at = datetime.now(UTC) - timedelta(days=40)
    ended.expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.flush()


async def seed_journal_combined(session: AsyncSession, telegram_id: int) -> None:
    """Checkpoint 4C (issue #188) — один пользователь для полного combined
    Journal acceptance: одна legacy Workout запись (тот же рецепт, что
    seed_ready — record_workout напрямую, не через API) + реальная STEP-
    программа "Подтягивания" (тот же рецепт, что
    seed_plan_week_start_session, свежая инклюзия без истории v2-сессий —
    readiness "ready" гарантирован) + два manual PlanItem, размещённых по
    дням (тот же рецепт, что seed_plan_week_manual_session). Ни одна v2-
    сессия ещё не начата — Golden Journey (раздел 15 задачи) проходит их
    вживую через Playwright, не заранее готовыми записями."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="e2e")
    now = datetime.now(UTC)
    onboarding = OnboardingService(session)
    _baseline, workout_set, _user = await onboarding.record_baseline_and_start(
        user_id=user.id, performed_at=now, reps=10,
    )
    await onboarding.complete_questionnaire_and_start_trial(user_id=user.id, now=now, **_QUESTIONNAIRE_DEFAULTS)
    band_item = await EquipmentItemRepository(session).create(
        user_id=user.id, name="Резина 15кг", resistance_kg=BAND_VALUE,
    )
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=10),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        block_a_equipment_item_id=band_item.id, block_b_equipment_item_id=band_item.id,
    )  # legacy-история — должна остаться видна после combined Journal (раздел 16)

    await seed_exercise_library(session)

    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Подтягивания", goal="e2e", structure_type=ProgramStructureType.RECURRING,
        category="e2e_journal_combined", progression_strategy_id=profile.id,
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
    )
    session.add(program)
    await session.flush()
    block_a = Exercise(name="Блок A", metric_type=MetricType.REPS, category="e2e_journal_combined", subcategory="block_a")
    block_b = Exercise(name="Блок Б", metric_type=MetricType.REPS, category="e2e_journal_combined", subcategory="block_b")
    session.add_all([block_a, block_b])
    await session.flush()
    session.add_all([
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_a.id,
            count_per_week=3, day_of_week=None,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=block_b.id,
            count_per_week=3, day_of_week=None,
        ),
    ])
    await session.flush()
    await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )

    plan = await TrainingPlanRepository(session).get_or_create_for_user(user.id)
    today = now.date()
    week_number = plan_week_number(plan.created_at.date(), today)
    week_start = plan_week_start_date(plan.created_at.date(), week_number)
    week = await TrainingPlanRepository(session).create_plan_week(
        training_plan_id=plan.id, week_number=week_number, start_date=week_start, phase=WeekPhase.BASE,
    )
    plank = (await session.execute(select(Exercise).where(Exercise.name == "Планка", Exercise.owner_user_id.is_(None)))).scalar_one()
    pushups = (await session.execute(select(Exercise).where(Exercise.name == "Отжимания", Exercise.owner_user_id.is_(None)))).scalar_one()
    session.add_all([
        PlanItem(
            training_plan_id=plan.id, exercise_id=plank.id, count_per_week=1,
            day_of_week=2, program_inclusion_id=None, plan_week_id=week.id,
        ),
        PlanItem(
            training_plan_id=plan.id, exercise_id=pushups.id, count_per_week=1,
            day_of_week=4, program_inclusion_id=None, plan_week_id=week.id,
        ),
    ])
    await session.flush()


async def seed_builder_workouts(session: AsyncSession, telegram_id: int) -> Exercise:
    """REBUILD-1 — пять пользовательских Builder Workout в текущей неделе:
    по одному на протокол (reps/time/max/interval) и смешанная
    reps -> interval -> max. Интервал короткий (15 с) — истечение в середине
    тренировки проверяется реальным временем."""
    user = await _onboard(session, telegram_id)
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    today = datetime.now(UTC).date()
    week_number = plan_week_number(plan.created_at.date(), today)
    week = await TrainingPlanRepository(session).create_plan_week(
        training_plan_id=plan.id, week_number=week_number,
        start_date=plan_week_start_date(plan.created_at.date(), week_number), phase=WeekPhase.BASE,
    )

    pull = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="e2e_builder", source_type="user", owner_user_id=user.id)
    plank = Exercise(name="Планка", metric_type=MetricType.TIME, category="e2e_builder", source_type="user", owner_user_id=user.id)
    push = Exercise(name="Отжимания", metric_type=MetricType.REPS, category="e2e_builder", source_type="user", owner_user_id=user.id)
    burpee = Exercise(name="Бёрпи", metric_type=MetricType.REPS, category="e2e_builder", source_type="user", owner_user_id=user.id)
    session.add_all([pull, plank, push, burpee])
    await session.flush()

    reps = {"type": "reps_sets", "rest_seconds": 2, "prescription": {"source": "static", "sets": 2, "reps": 8}}
    time_ = {"type": "time_sets", "rest_seconds": 2, "prescription": {"source": "static", "sets": 2, "duration_seconds": 30}}
    max_ = {"type": "max_effort", "rest_seconds": 2, "prescription": {"source": "static", "attempts": 2}}
    interval = {"type": "interval", "total_duration_seconds": 15, "work_seconds": 5, "rest_seconds": 5, "starts_with": "work"}

    workouts = [
        ("Только reps", [(pull, reps)]),
        ("Только time", [(plank, time_)]),
        ("Только max", [(push, max_)]),
        ("Только interval", [(burpee, interval)]),
        ("Смешанная", [(pull, reps), (burpee, interval), (push, max_)]),
        ("Дубли", [(pull, reps), (plank, time_), (pull, max_)]),
    ]
    for day, (title, items) in enumerate(workouts):
        workout = Complex(name=title, source_type="user", owner_user_id=user.id)
        session.add(workout)
        await session.flush()
        for index, (exercise, protocol) in enumerate(items):
            session.add(ComplexItem(
                complex_id=workout.id, exercise_id=exercise.id, order_index=index, sets=0, protocol=protocol,
            ))
        session.add(PlanItem(
            training_plan_id=plan.id, exercise_id=items[0][0].id, complex_id=workout.id, count_per_week=1,
            day_of_week=day % 7, program_inclusion_id=None, plan_week_id=week.id,
        ))
    await session.flush()
    return pull


async def seed_journal_v2(session: AsyncSession, telegram_id: int) -> None:
    """REBUILD-1 (R2) — те же Builder Workout, что builder_workouts, плюс 30
    завершённых "исторических" сессий (без снимка — их удалять нельзя) для
    пагинации Журнала (>25). Сессии разнесены по времени, самая свежая — №0."""
    pull = await seed_builder_workouts(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    repo = TrainingSessionRepository(session)
    now = datetime.now(UTC)
    for index in range(30):
        await repo.create_session(
            # минуты, не дни: Журнал листается по месяцам (#256) — все 30 сессий
            # должны остаться в том же месяце, что и живые тренировки теста.
            user_id=user.id, source=SessionSource.PLAN, performed_at=now - timedelta(minutes=5 + index),
            effort=None, comment=None,
            blocks=[SessionBlockInput(exercise_id=pull.id, sets=[
                SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(10 + index), unit="reps"),
                SetLogInput(set_number=2, metric_type=MetricType.REPS, value=Decimal(9 + index), unit="reps"),
            ])],
        )
    await session.flush()


async def seed_journal_calendar(session: AsyncSession, telegram_id: int) -> None:
    """#256 — календарь Журнала (пояс Europe/Moscow): завершённые сессии без
    снимка в ПРЕДЫДУЩЕМ месяце — 10-го, дважды 15-го и 20-го в 12:00 МСК — и
    одна сессия «только что» в текущем месяце. Остальные дни и месяц до
    предыдущего пусты."""
    from zoneinfo import ZoneInfo

    user = await _onboard(session, telegram_id)
    tz = ZoneInfo("Europe/Moscow")
    user.timezone = "Europe/Moscow"
    pull = Exercise(
        name="Подтягивания", metric_type=MetricType.REPS, category="e2e_journal_calendar",
        source_type="user", owner_user_id=user.id,
    )
    session.add(pull)
    await session.flush()
    repo = TrainingSessionRepository(session)
    now = datetime.now(UTC)
    local_today = now.astimezone(tz).date()
    previous_month_last = local_today.replace(day=1) - timedelta(days=1)

    async def add(at: datetime, reps: int) -> None:
        await repo.create_session(
            user_id=user.id, source=SessionSource.PLAN, performed_at=at, effort=None, comment=None,
            blocks=[SessionBlockInput(exercise_id=pull.id, sets=[
                SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(reps), unit="reps"),
            ])],
        )

    for day, hour, reps in ((10, 12, 8), (15, 12, 9), (15, 18, 10), (20, 12, 11)):
        at = datetime(previous_month_last.year, previous_month_last.month, day, hour, tzinfo=tz)
        await add(at.astimezone(UTC), reps)
    await add(now - timedelta(minutes=5), 12)
    await session.flush()


async def seed_journal_return(session: AsyncSession, telegram_id: int) -> None:
    """#284 C — Back из «Открыть тренировку» возвращает в тот же месяц Журнала с той же записью.
    Как journal_calendar (прошлый месяц: 10-го, дважды 15-го, 20-го; плюс сессия сегодня), но
    сессии прошлого месяца привязаны к своей тренировке «Возвратная тренировка» (снимок с workout_id)."""
    await seed_journal_calendar(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    pull = (await session.execute(select(Exercise).where(Exercise.owner_user_id == user.id))).scalars().one()
    workout = Complex(name="Возвратная тренировка", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    protocol = {"type": "reps_sets", "rest_seconds": 60, "prescription": {"source": "static", "sets": 1, "reps": 8}}
    session.add(ComplexItem(complex_id=workout.id, exercise_id=pull.id, order_index=0, sets=1, protocol=protocol))
    sessions = (await session.execute(
        select(TrainingSession).where(TrainingSession.user_id == user.id).order_by(TrainingSession.performed_at),
    )).scalars().all()
    for training in sessions[:-1]:  # все, кроме сегодняшней
        training.workout_snapshot = {"workout_id": workout.id, "title": workout.name, "items": []}
    await session.flush()


async def seed_journal_edit(session: AsyncSession, telegram_id: int) -> None:
    """#262 — правка/клон из Журнала (пояс Europe/Moscow). Две завершённые сессии
    сегодня: Builder «Моя силовая» со снимком (can_edit; 2 подхода — второй с
    усилием и заметкой, усилие тренировки 3, комментарий) — 5 минут назад, и
    историческая без снимка («Тренировка», can_edit=false) — 10 минут назад."""
    user = await _onboard(session, telegram_id)
    user.timezone = "Europe/Moscow"
    pull = Exercise(
        name="Подтягивания", metric_type=MetricType.REPS, category="e2e_journal_edit",
        source_type="user", owner_user_id=user.id,
    )
    session.add(pull)
    workout = Complex(name="Моя силовая", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    protocol = {"type": "reps_sets", "rest_seconds": 60, "prescription": {"source": "static", "sets": 2, "reps": 8}}
    session.add(ComplexItem(complex_id=workout.id, exercise_id=pull.id, order_index=0, sets=2, protocol=protocol))
    now = datetime.now(UTC)
    training = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED,
        performed_at=now - timedelta(minutes=5), completed_at=now - timedelta(minutes=1),
        effort=Decimal(3), comment="Было нормально",
        workout_snapshot={
            "workout_id": workout.id, "title": "Моя силовая",
            "items": [{
                "exercise_id": pull.id, "exercise_name": pull.name, "order": 0,
                # снимок хранит РАЗРЕШЁННЫЙ протокол (по подходам), не определение
                "protocol": {"type": "reps_sets", "sets": [{"target_reps": 8}, {"target_reps": 8}], "rest_seconds": 60},
            }],
        },
    )
    session.add(training)
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    plan_item = PlanItem(
        training_plan_id=plan.id, exercise_id=pull.id, complex_id=workout.id, count_per_week=1, day_of_week=1,
    )
    session.add(plan_item)
    await session.flush()
    session.add(SessionPlanItem(session_id=training.id, plan_item_id=plan_item.id))  # заголовок «Моя силовая»
    block = SessionBlock(session_id=training.id, order_index=0, exercise_id=pull.id)
    session.add(block)
    await session.flush()
    session.add(SetTarget(
        session_block_id=block.id, set_number=1, metric_type=MetricType.REPS, value=Decimal(8), unit="reps",
    ))
    session.add(SetLog(
        session_block_id=block.id, set_number=1, metric_type=MetricType.REPS, value=Decimal(8), unit="reps",
    ))
    session.add(SetLog(
        session_block_id=block.id, set_number=2, metric_type=MetricType.REPS, value=Decimal(7), unit="reps",
        effort=Decimal(4), note="Последние тяжело",
    ))
    await TrainingSessionRepository(session).create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=now - timedelta(minutes=10), effort=None,
        comment=None, completed_at=now - timedelta(minutes=9),
        blocks=[SessionBlockInput(exercise_id=pull.id, sets=[
            SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(5), unit="reps"),
        ])],
    )
    await session.flush()


async def seed_journal_plans_polish(session: AsyncSession, telegram_id: int) -> None:
    """#277 journal/plans polish — как journal_edit, но тренировка плана с длинным названием (title + снимок),
    плюс запись задним числом (самый длинный бейдж) и «Активность»; строка дня плана уже выполнена (1/1)."""
    await seed_journal_edit(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    long_title = "Силовая тренировка верхней части тела с подтягиваниями и отжиманиями"
    workout = (await session.execute(
        select(Complex).where(Complex.owner_user_id == user.id, Complex.name == "Моя силовая"),
    )).scalar_one()
    workout.name = long_title
    for training in (await session.execute(
        select(TrainingSession).where(TrainingSession.user_id == user.id, TrainingSession.workout_snapshot.is_not(None)),
    )).scalars():
        training.workout_snapshot = {**training.workout_snapshot, "title": long_title}
    pull = (await session.execute(
        select(Exercise).where(Exercise.owner_user_id == user.id, Exercise.name == "Подтягивания"),
    )).scalar_one()
    # Строка плана — в текущей неделе: сегодняшняя сессия уже выполнила её (1/1).
    plan = (await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))).scalar_one()
    today = datetime.now(UTC).date()
    current_number = plan_week_number(plan.created_at.date(), today)
    week = await TrainingPlanRepository(session).create_plan_week(
        training_plan_id=plan.id, week_number=current_number,
        start_date=plan_week_start_date(plan.created_at.date(), current_number), phase=WeekPhase.BASE,
    )
    plan_item = (await session.execute(select(PlanItem).where(PlanItem.training_plan_id == plan.id))).scalar_one()
    plan_item.plan_week_id = week.id
    now = datetime.now(UTC)
    await TrainingSessionRepository(session).create_session(
        user_id=user.id, source=SessionSource.BACKDATED, performed_at=now - timedelta(minutes=20), effort=None,
        comment=None, completed_at=now - timedelta(minutes=19),
        blocks=[SessionBlockInput(exercise_id=pull.id, sets=[
            SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(6), unit="reps"),
        ])],
    )
    await session.flush()


async def seed_analytics_v2(session: AsyncSession, telegram_id: int) -> None:
    """REBUILD-1 (R3) — детерминированные данные для Analytics v2 (часовой
    пояс Pacific/Kiritimati, +14):
      * 205 старых сессий (40+ дней назад, только "Подтягивания" reps) —
        всего сессий >200 (аналитика не зависит от страниц Журнала);
      * max 10 дней назад (19, точка отсчёта), time 9 дней назад, смешанная
        (reps -> interval -> max 21 того же упражнения) 8 дней назад — новый
        рекорд;
      * граничная сессия: понедельник текущей ЛОКАЛЬНОЙ недели 00:30 по
        местному времени (в UTC это воскресенье прошлой недели);
    в окне 30 дней ровно 4 сессии."""
    from zoneinfo import ZoneInfo

    user = await _onboard(session, telegram_id)
    user.timezone = "Pacific/Kiritimati"
    tz = ZoneInfo("Pacific/Kiritimati")
    pull = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="e2e_analytics", source_type="user", owner_user_id=user.id)
    plank = Exercise(name="Планка", metric_type=MetricType.TIME, category="e2e_analytics", source_type="user", owner_user_id=user.id)
    burpee = Exercise(name="Бёрпи", metric_type=MetricType.REPS, category="e2e_analytics", source_type="user", owner_user_id=user.id)
    session.add_all([pull, plank, burpee])
    await session.flush()

    reps = {"type": "reps_sets", "sets": [{"target_reps": 8}], "rest_seconds": 0}
    time_ = {"type": "time_sets", "sets": [{"target_seconds": 30}], "rest_seconds": 0}
    max_ = {"type": "max_effort", "attempts": [{"is_max": True}], "rest_seconds": 0}
    interval = {"type": "interval", "total_duration_seconds": 60, "work_seconds": 10, "rest_seconds": 20, "starts_with": "work"}

    async def add(at: datetime, blocks: list[tuple[Exercise, dict, list[int], dict | None]]) -> None:
        training = TrainingSession(
            user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED, performed_at=at,
            workout_snapshot={
                "workout_id": 1, "title": "Аналитика",
                "items": [
                    {"exercise_id": ex.id, "exercise_name": ex.name, "order": i, "protocol": proto}
                    for i, (ex, proto, _, _) in enumerate(blocks)
                ],
            },
        )
        session.add(training)
        await session.flush()
        for index, (exercise, _proto, values, result) in enumerate(blocks):
            block = SessionBlock(session_id=training.id, order_index=index, exercise_id=exercise.id, result=result)
            session.add(block)
            await session.flush()
            unit = "s" if exercise.metric_type == MetricType.TIME else "reps"
            for number, value in enumerate(values, start=1):
                session.add(SetLog(
                    session_block_id=block.id, set_number=number, metric_type=exercise.metric_type,
                    value=Decimal(value), unit=unit,
                ))

    now = datetime.now(UTC)
    for i in range(205):
        await add(now - timedelta(days=40, minutes=i), [(pull, reps, [5, 4], None)])
    interval_result = {"type": "interval", "actual_duration_seconds": 60, "completed_cycles": 2}
    await add(now - timedelta(days=8), [(pull, reps, [8, 7], None), (burpee, interval, [], interval_result), (pull, max_, [21], None)])
    await add(now - timedelta(days=9), [(plank, time_, [30, 25], None)])
    await add(now - timedelta(days=10), [(pull, max_, [19], None)])
    local_today = now.astimezone(tz).date()
    local_monday = local_today - timedelta(days=local_today.weekday())
    boundary = datetime.combine(local_monday, datetime.min.time(), tzinfo=tz) + timedelta(minutes=30)
    await add(boundary, [(pull, reps, [5], None)])
    await session.flush()


async def seed_analytics_metric(session: AsyncSession, telegram_id: int) -> None:
    """#259 — метрика «Тренировки / Минуты» (часовой пояс по умолчанию, МСК):
      * 3 дня назад — 40 мин, 5 дней назад — 30 мин (обе в окне 1 мес);
      * 6 дней назад — без completed_at («без данных о времени»);
      * 50 дней назад — 60 мин (виден только в 3 мес и в «Свой»).
    1 мес: 3 тренировки / 70 мин / 1 без времени; 3 мес: 4 / 130 / 1."""
    user = await _onboard(session, telegram_id)
    now = datetime.now(UTC)
    for days_ago, minutes in ((3, 40), (5, 30), (6, None), (50, 60)):
        performed_at = now - timedelta(days=days_ago)
        session.add(TrainingSession(
            user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED, performed_at=performed_at,
            completed_at=None if minutes is None else performed_at + timedelta(minutes=minutes),
        ))
    await session.flush()


async def seed_tests_hub(session: AsyncSession, telegram_id: int) -> None:
    """#260 — хаб «Тесты»: онбордящийся пользователь с двумя замерами «Максимум подтягиваний»
    (10 повт. 20 дней назад, 12 повт. 5 дней назад); остальные протоколы (засеяны миграцией)
    без результатов. Протоколы берутся по имени — сид их не создаёт."""
    user = await _onboard(session, telegram_id)
    protocol = (await session.execute(
        select(AssessmentProtocol).where(AssessmentProtocol.name == "Максимум подтягиваний"),
    )).scalar_one()
    now = datetime.now(UTC)
    for days_ago, value in ((20, 10), (5, 12)):
        session.add(AssessmentResult(
            user_id=user.id, protocol_id=protocol.id, performed_at=now - timedelta(days=days_ago),
            value=value, unit="повт.",
        ))
    await session.flush()


# --- Peer Insights (#276) ------------------------------------------------------------------
# Синтетическая популяция живёт в ОТДЕЛЬНЫХ id-диапазонах (только e2e-БД): женщины 8_100_001..,
# мужчины 8_200_001... Они пересоздаются при каждом сиде зрителя, так что число и значения всегда
# одни и те же. Все — 30–39 лет (середина ступени), результат — только «Подтягивания с весом, кг».
_PEER_POPULATION_VALUES = [v for v in range(1, 26) if v != 10]  # 24 значения; зритель — 10 кг
_PEER_WEIGHTED_PROTOCOL = "Подтягивания с весом, кг"
_PEER_FEMALE_BASE = 8_100_000
_PEER_MALE_BASE = 8_200_000


def _peer_birth_date() -> date:
    return date(datetime.now(UTC).year - 35, 1, 15)


async def _peer_protocol_id(session: AsyncSession, name: str) -> int:
    return (await session.execute(select(AssessmentProtocol.id).where(AssessmentProtocol.name == name))).scalar_one()


async def _seed_peer_viewer(session: AsyncSession, telegram_id: int, gender: Gender, base: int) -> None:
    """Зритель (гендер + 35 лет, 10 кг) + 24 синтетических пользователя той же когорты (значения
    1..25 кг кроме 10): когорта = 25 человек, процентиль 38, медиана 13, следующий порог — p50 = 13 кг."""
    users = UserRepository(session)
    for offset in range(1, len(_PEER_POPULATION_VALUES) + 1):
        stale = await users.get_by_telegram_id(base + offset)
        if stale is not None:
            await _purge_user(session, stale.id)
    viewer = await _onboard(session, telegram_id)
    viewer.gender, viewer.birth_date = gender, _peer_birth_date()
    protocol_id = await _peer_protocol_id(session, _PEER_WEIGHTED_PROTOCOL)
    now = datetime.now(UTC)
    session.add(AssessmentResult(
        user_id=viewer.id, protocol_id=protocol_id, performed_at=now - timedelta(days=3), value=10, unit="кг",
    ))
    for offset, value in enumerate(_PEER_POPULATION_VALUES, start=1):
        peer = await users.create(telegram_id=base + offset, username=f"peer{base + offset}")
        peer.gender, peer.birth_date = gender, _peer_birth_date()
        session.add(AssessmentResult(
            user_id=peer.id, protocol_id=protocol_id, performed_at=now - timedelta(days=2), value=value, unit="кг",
        ))
    await session.flush()


async def seed_peer_cohort_female(session: AsyncSession, telegram_id: int) -> None:
    await _seed_peer_viewer(session, telegram_id, Gender.FEMALE, _PEER_FEMALE_BASE)


async def seed_peer_cohort_male(session: AsyncSession, telegram_id: int) -> None:
    await _seed_peer_viewer(session, telegram_id, Gender.MALE, _PEER_MALE_BASE)


async def seed_peer_insufficient(session: AsyncSession, telegram_id: int) -> None:
    """Зритель с одним результатом «Максимум подтягиваний» (12): в e2e-БД нет ни одной когорты на 20
    человек по этому протоколу -> «Пока мало данных для сравнения»."""
    viewer = await _onboard(session, telegram_id)
    viewer.gender, viewer.birth_date = Gender.MALE, _peer_birth_date()
    session.add(AssessmentResult(
        user_id=viewer.id, protocol_id=await _peer_protocol_id(session, "Максимум подтягиваний"),
        performed_at=datetime.now(UTC) - timedelta(days=4), value=12, unit="повт.",
    ))
    await session.flush()


async def seed_peer_empty(session: AsyncSession, telegram_id: int) -> None:
    """Онбордящийся зритель без результатов тестов (состояние «нет результата», затем запись)."""
    viewer = await _onboard(session, telegram_id)
    viewer.gender, viewer.birth_date = Gender.FEMALE, _peer_birth_date()
    await session.flush()


async def seed_home_workouts(session: AsyncSession, telegram_id: int) -> None:
    """G3 — Главная/«Мои тренировки»: у пользователя две своих Workout (одна
    с длинным русским названием и тремя упражнениями, одна пустая) и
    чужая Workout другого пользователя, которая на Главной появляться не
    должна. Каталог Программ приходит из миграций."""
    user = await _onboard(session, telegram_id)
    foreign_telegram_id = telegram_id + 1_000_000
    foreign_existing = await UserRepository(session).get_by_telegram_id(foreign_telegram_id)
    if foreign_existing is not None:
        await _purge_user(session, foreign_existing.id)
    foreign = await _onboard(session, foreign_telegram_id)

    def exercise(name: str, owner: User) -> Exercise:
        return Exercise(name=name, metric_type=MetricType.REPS, category="e2e_home", source_type="user", owner_user_id=owner.id)

    pull, push, plank = exercise("Подтягивания", user), exercise("Отжимания", user), exercise("Планка", user)
    foreign_ex = exercise("Чужое упражнение", foreign)
    session.add_all([pull, push, plank, foreign_ex])
    await session.flush()
    reps = {"type": "reps_sets", "rest_seconds": 0, "prescription": {"source": "static", "sets": 3, "reps": 8}}
    workouts = [
        (user, "Очень длинная утренняя тренировка на все группы мышц и выносливость", [(pull, reps), (push, reps), (plank, reps)]),
        (user, "Пустая заготовка", []),
        (foreign, "Чужая тренировка", [(foreign_ex, reps)]),
    ]
    for owner, title, items in workouts:
        workout = Complex(name=title, source_type="user", owner_user_id=owner.id)
        session.add(workout)
        await session.flush()
        for index, (ex, protocol) in enumerate(items):
            session.add(ComplexItem(complex_id=workout.id, exercise_id=ex.id, order_index=index, sets=0, protocol=protocol))
    await session.flush()


async def seed_home_discovery(session: AsyncSession, telegram_id: int) -> None:
    """#254 — Главная как витрина: свои тренировки/упражнения как у home_workouts +
    программы каталога минимум в двух категориях (глобальные, find-or-create по имени)
    и одна без категории (ряд «Другое»)."""
    await seed_home_workouts(session, telegram_id)
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    for name, category in (
        ("Дискавери: сила", "e2e_discovery_strength"),
        ("Дискавери: гибкость", "e2e_discovery_mobility"),
        ("Дискавери: без категории", None),
    ):
        existing = (await session.execute(select(Program).where(Program.name == name))).scalars().first()
        if existing is None:
            session.add(Program(
                name=name, goal=f"цель {name}", structure_type=ProgramStructureType.RECURRING,
                category=category, progression_strategy_id=profile.id,
                config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
            ))
    await session.flush()


async def seed_workout_detail(session: AsyncSession, telegram_id: int) -> None:
    """#255 — Workout Detail: свои тренировки как у home_workouts + «Интервальная»
    (time_sets, чтобы была оценка длительности) и две завершённые сессии «Очень длинной…»
    со снимком (одна без снимка и одна чужой тренировки на историю не влияют)."""
    await seed_home_workouts(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    long_workout = (await session.execute(
        select(Complex).where(Complex.owner_user_id == user.id, Complex.name.like("Очень длинная%")),
    )).scalars().one()
    plank = (await session.execute(
        select(Exercise).where(Exercise.owner_user_id == user.id, Exercise.name == "Планка"),
    )).scalars().one()
    timed = Complex(name="Планка по времени", source_type="user", owner_user_id=user.id)
    session.add(timed)
    await session.flush()
    session.add(ComplexItem(
        complex_id=timed.id, exercise_id=plank.id, order_index=0, sets=0,
        protocol={"type": "time_sets", "rest_seconds": 60, "prescription": {"source": "static", "sets": 3, "duration_seconds": 30}},
    ))
    repo = TrainingSessionRepository(session)
    now = datetime.now(UTC)
    for days_ago, sets in ((7, 2), (2, 3)):
        training = await repo.create_session(
            user_id=user.id, source=SessionSource.PLAN, performed_at=now - timedelta(days=days_ago),
            effort=None, comment=None,
            blocks=[SessionBlockInput(exercise_id=plank.id, sets=[
                SetLogInput(set_number=n, metric_type=MetricType.REPS, value=Decimal(8), unit="reps")
                for n in range(1, sets + 1)
            ])],
        )
        training.workout_snapshot = {"workout_id": long_workout.id, "title": long_workout.name, "items": []}
    await session.flush()


async def seed_golden_journey(session: AsyncSession, telegram_id: int) -> None:
    """GJ — Golden Journey: вернувшийся пользователь с одной своей Workout
    («Золотая тренировка», reps 2 x 8) и пустой текущей неделей плана — её ещё
    нужно добавить в план, начать, завершить, увидеть в Аналитике/Журнале."""
    user = await _onboard(session, telegram_id)
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    today = datetime.now(UTC).date()
    week_number = plan_week_number(plan.created_at.date(), today)
    await TrainingPlanRepository(session).create_plan_week(
        training_plan_id=plan.id, week_number=week_number,
        start_date=plan_week_start_date(plan.created_at.date(), week_number), phase=WeekPhase.BASE,
    )
    pull = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="e2e_golden", source_type="user", owner_user_id=user.id)
    session.add(pull)
    await session.flush()
    workout = Complex(name="Золотая тренировка", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    protocol = {"type": "reps_sets", "rest_seconds": 2, "prescription": {"source": "static", "sets": 2, "reps": 8}}
    session.add(ComplexItem(complex_id=workout.id, exercise_id=pull.id, order_index=0, sets=0, protocol=protocol))
    await session.flush()


async def seed_sweep_defects(session: AsyncSession, telegram_id: int) -> None:
    """#277 «Sweep defects»: golden_journey (своя Workout «Золотая тренировка», план без курсов — D3,
    Журнал пуст — D1) + две завершённые v2-сессии (2 и 5 дней назад) и НИ ОДНОЙ legacy-тренировки (D2:
    Профиль должен учесть Журнал v2, а не показать «Тренировок пока не было.»)."""
    await seed_golden_journey(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    exercise = (await session.execute(
        select(Exercise).where(Exercise.owner_user_id == user.id, Exercise.name == "Подтягивания"),
    )).scalar_one()
    repo = TrainingSessionRepository(session)
    now = datetime.now(UTC)
    for days_ago in (2, 5):
        at = now - timedelta(days=days_ago)
        await repo.create_session(
            user_id=user.id, source=SessionSource.BACKDATED, performed_at=at, effort=None, comment=None,
            completed_at=at,
            blocks=[SessionBlockInput(exercise_id=exercise.id, sets=[
                SetLogInput(set_number=n, metric_type=MetricType.REPS, value=Decimal(value), unit="reps")
                for n, value in enumerate((8, 7), start=1)
            ])],
        )
    await session.flush()


async def seed_session_recovery(session: AsyncSession, telegram_id: int) -> None:
    """Восстановление активной сессии (issue #246): одна своя Workout, reps
    3 x 8 с отдыхом 60 с — достаточно длинный, чтобы фон/перезагрузка
    происходили посреди отдыха. Старт — из свободного пула «Планов» (как у
    golden_journey); admin не нужен."""
    await seed_golden_journey(session, telegram_id)
    workout = (
        await session.execute(
            select(Complex).where(Complex.owner_user_id == (await UserRepository(session).get_by_telegram_id(telegram_id)).id)
        )
    ).scalar_one()
    workout.name = "Тренировка восстановления"
    item = (await session.execute(select(ComplexItem).where(ComplexItem.complex_id == workout.id))).scalar_one()
    item.protocol = {"type": "reps_sets", "rest_seconds": 60, "prescription": {"source": "static", "sets": 3, "reps": 8}}
    await session.flush()


async def seed_background_interval(session: AsyncSession, telegram_id: int) -> None:
    """#269 «Background timer»: та же свободная Workout, что у session_recovery, но
    interval 180 с (работа 10 / отдых 20) — достаточно длинный, чтобы сдвигать часы
    браузера через границы фаз, не доходя до дедлайна блока."""
    await seed_session_recovery(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    workout = (await session.execute(select(Complex).where(Complex.owner_user_id == user.id))).scalar_one()
    workout.name = "Интервал фона"
    item = (await session.execute(select(ComplexItem).where(ComplexItem.complex_id == workout.id))).scalar_one()
    item.protocol = {
        "type": "interval", "total_duration_seconds": 180, "work_seconds": 10, "rest_seconds": 20,
        "starts_with": "work",
    }
    await session.flush()


async def seed_analytics_distribution(session: AsyncSession, telegram_id: int) -> None:
    """#274 «Analytics distribution»: свои упражнения категорий e2e_dist_pull (подкатегории
    vertical/horizontal), e2e_dist_core, e2e_dist_legs (без тренировок — строка с нулями) и сессии:
      * 3 дня назад — pull/vertical, 40 мин; 5 дней назад — pull/horizontal + core (50/50), 20 мин;
      * 6 дней назад — свободная активность «Бег», 30 мин; 50 дней назад — core, 60 мин (виден с 3 мес).
    1 мес: pull 1.5/50 (vertical 1/40, horizontal 0.5/10), core 0.5/10, legs 0/0, «Другая активность»
    1/30; итого 3 / 90. 3 мес: core 1.5/70, итого 4 / 150."""
    user = await _onboard(session, telegram_id)

    def exercise(name: str, category: str, subcategory: str | None = None) -> Exercise:
        return Exercise(
            name=name, metric_type=MetricType.REPS, category=category, subcategory=subcategory,
            source_type="user", owner_user_id=user.id,
        )

    vertical = exercise("Тяга вертикальная", "e2e_dist_pull", "vertical")
    horizontal = exercise("Тяга горизонтальная", "e2e_dist_pull", "horizontal")
    core = exercise("Пресс", "e2e_dist_core")
    legs = exercise("Приседания", "e2e_dist_legs")
    session.add_all([vertical, horizontal, core, legs])
    await session.flush()

    async def add(days_ago: int, minutes: int, exercises: list[Exercise], activity_type: str | None = None) -> None:
        at = datetime.now(UTC) - timedelta(days=days_ago)
        training = TrainingSession(
            user_id=user.id, source=SessionSource.FREEFORM if activity_type else SessionSource.PLAN,
            status=SessionStatus.COMPLETED, performed_at=at,
            completed_at=None if activity_type else at + timedelta(minutes=minutes),
            activity_type=activity_type, duration_seconds=minutes * 60 if activity_type else None,
        )
        session.add(training)
        await session.flush()
        for index, item in enumerate(exercises):
            session.add(SessionBlock(session_id=training.id, order_index=index, exercise_id=item.id))

    await add(3, 40, [vertical])
    await add(5, 20, [horizontal, core])
    await add(6, 30, [], activity_type="running")
    await add(50, 60, [core])
    await session.flush()


async def seed_body_metrics(session: AsyncSession, telegram_id: int) -> None:
    """#270 «Body metrics»: онбординг (вес 75 кг / рост 180 см = текущая запись истории «сейчас»)
    + два задним числом замера веса: 78 кг (30 дней назад) и 76.5 кг (14 дней назад)."""
    user = await _onboard(session, telegram_id)
    history = BodyMetricRepository(session)
    now = datetime.now(UTC)
    await history.add(user.id, BodyMetric.WEIGHT_KG, Decimal(78), now - timedelta(days=30))
    await history.add(user.id, BodyMetric.WEIGHT_KG, Decimal("76.5"), now - timedelta(days=14))


async def seed_sweep_empty(session: AsyncSession, telegram_id: int) -> None:
    """#277 «Full sweep» — пустой пользователь: онбординг пройден, ни тренировок, ни плана, ни
    истории, ни замеров (каталог программ глобальный и приходит из миграций)."""
    user = await _onboard(session, telegram_id)
    user.timezone = "Europe/Moscow"
    await session.flush()


async def seed_sweep_populated(session: AsyncSession, telegram_id: int) -> None:
    """#277 «Full sweep» — наполненный пользователь (МСК):
      * план: прошлая и текущая недели (plan_week_stepper: «Планка» 1/2, «Отжимания» 0/1, прошлая 1/1)
        + подключённый курс «Свип: курс» (вторник + свободный пул);
      * своя Workout «Свип: тренировка» (reps 2 x 8, отдых 2 с) в избранном;
      * Журнал/Аналитика: сессии 2 и 4 дня назад («Подтягивания», с подходами и временем), 9 дней
        назад (с подходами), «Бег» 30 мин 3 дня назад и 50 дней назад (виден в «3 мес»);
      * Тесты: «Вис на перекладине» 30 → 40 сек (НЕ «Максимум подтягиваний» / «…с весом»: по ним e2e-БД держит
        точные когорты Peer Insights #276 — десятки наших пользователей их бы сломали); Профиль: вес 78 → 76.5 кг (история);
      * два факультатива (#279) в Журнале: 30 и 90 минут назад."""
    await seed_plan_week_stepper(session, telegram_id)
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    user.timezone = "Europe/Moscow"
    now = datetime.now(UTC)

    pull = Exercise(
        name="Подтягивания", metric_type=MetricType.REPS, category="e2e_sweep",
        source_type="user", owner_user_id=user.id,
    )
    session.add(pull)
    await session.flush()
    workout = Complex(name="Свип: тренировка", source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    protocol = {"type": "reps_sets", "rest_seconds": 2, "prescription": {"source": "static", "sets": 2, "reps": 8}}
    session.add(ComplexItem(complex_id=workout.id, exercise_id=pull.id, order_index=0, sets=0, protocol=protocol))
    session.add(UserFavorite(user_id=user.id, target_type="workout", target_id=workout.id))
    await session.flush()

    program = (await session.execute(select(Program).where(Program.name == "Свип: курс"))).scalars().first()
    if program is None:
        plank = (await session.execute(
            select(Exercise).where(Exercise.name == "Планка", Exercise.owner_user_id.is_(None)),
        )).scalar_one()
        program = Program(
            name="Свип: курс", goal="цель: свип", structure_type=ProgramStructureType.RECURRING,
            category="e2e_sweep", config={"duration_weeks": 8},
        )
        session.add(program)
        await session.flush()
        session.add_all([
            ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=plank.id, count_per_week=1, day_of_week=1),
            ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=plank.id, count_per_week=2, day_of_week=None),
        ])
        await session.flush()
    await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )

    repo = TrainingSessionRepository(session)
    for days_ago, reps in ((2, (8, 7)), (4, (9, 8)), (9, (10, 9))):
        at = now - timedelta(days=days_ago)
        await repo.create_session(
            user_id=user.id, source=SessionSource.PLAN, performed_at=at, effort=None, comment=None,
            completed_at=at + timedelta(minutes=30),
            blocks=[SessionBlockInput(exercise_id=pull.id, sets=[
                SetLogInput(set_number=n, metric_type=MetricType.REPS, value=Decimal(value), unit="reps")
                for n, value in enumerate(reps, start=1)
            ])],
        )
    for days_ago in (3, 50):
        at = now - timedelta(days=days_ago)
        session.add(TrainingSession(
            user_id=user.id, source=SessionSource.FREEFORM, status=SessionStatus.COMPLETED, performed_at=at,
            activity_type="running", duration_seconds=30 * 60,
        ))

    protocol_row = (await session.execute(
        select(AssessmentProtocol).where(AssessmentProtocol.name == "Вис на перекладине, сек"),
    )).scalar_one()
    for days_ago, value in ((20, 30), (5, 40)):
        session.add(AssessmentResult(
            user_id=user.id, protocol_id=protocol_row.id, performed_at=now - timedelta(days=days_ago),
            value=value, unit="сек",
        ))
    history = BodyMetricRepository(session)
    await history.add(user.id, BodyMetric.WEIGHT_KG, Decimal(78), now - timedelta(days=30))
    await history.add(user.id, BodyMetric.WEIGHT_KG, Decimal("76.5"), now - timedelta(days=14))
    await _seed_backfilled_electives(session, user)  # #279: два факультатива в Журнале (30 и 90 минут назад)
    await session.flush()


async def seed_collections_scenario(session: AsyncSession, telegram_id: int) -> None:
    """#271 «Collections»: онбордившийся пользователь + глобальные (find-or-create) две
    программы «Подборка: …», system-упражнение «Подборка: упражнение», приватное user-упражнение
    и две подборки: опубликованная «E2E: подборка» (2 программы + system- и приватное упражнение —
    приватное не должно показываться) и неопубликованный черновик (на Главной не виден)."""
    user = await _onboard(session, telegram_id)
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program_ids: list[int] = []
    for name, category in (("Подборка: сила", "e2e_collection_strength"), ("Подборка: гибкость", "e2e_collection_mobility")):
        program = (await session.execute(select(Program).where(Program.name == name))).scalars().first()
        if program is None:
            program = Program(
                name=name, goal=f"цель {name}", structure_type=ProgramStructureType.RECURRING,
                category=category, progression_strategy_id=profile.id,
                config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
            )
            session.add(program)
            await session.flush()
        program_ids.append(program.id)
    system_exercise = (await session.execute(
        select(Exercise).where(Exercise.name == "Подборка: упражнение", Exercise.source_type == "system"),
    )).scalars().first()
    if system_exercise is None:
        system_exercise = Exercise(
            name="Подборка: упражнение", metric_type=MetricType.REPS, category="e2e_collection", source_type="system",
        )
        session.add(system_exercise)
    private_exercise = Exercise(
        name="Подборка: приватное", metric_type=MetricType.REPS, category="e2e_collection",
        source_type="user", owner_user_id=user.id,
    )
    session.add(private_exercise)
    await session.flush()
    repo = CollectionRepository(session)
    await repo.upsert_collection(
        slug="e2e-collection", title="E2E: подборка", sort_order=-100,
        description="Подборка для E2E: две программы и упражнение, приватное содержимое скрыто.",
        program_ids=program_ids, exercise_ids=[system_exercise.id, private_exercise.id],
    )
    await repo.upsert_collection(
        slug="e2e-draft", title="E2E: черновик", description="Не опубликовано", sort_order=-99,
        is_published=False, program_ids=program_ids,
    )
    await session.flush()


async def seed_owner_optional_workout(session: AsyncSession, telegram_id: int) -> None:
    """#279 (P0 владельца) — «Факультатив — 3 минуты подтягиваний» в Журнале v2.

    Это НЕ PlanItem и не пользовательская Builder-тренировка: backfill волны 2
    (scripts/backfill_multi_program.py, #163) переносит legacy ElectiveWorkout в
    TrainingSession(source=elective) с блоком на системное Exercise «Факультатив — …»
    (subcategory elective_<тип>), без замороженного снимка и без SessionPlanItem; формат/
    снаряд упакованы JSON-ом в SetLog.note. Сид воспроизводит это ТЕМИ ЖЕ функциями backfill:
    два факультатива — «3 минуты подтягиваний» (30 минут назад, 3 интервала по 4+3+2) и
    «на максимум» (90 минут назад, 4 подхода)."""
    user = await _onboard(session, telegram_id)
    user.timezone = "Europe/Moscow"
    await _seed_backfilled_electives(session, user)


async def _seed_backfilled_electives(session: AsyncSession, user: User) -> None:
    """Два факультатива пользователя (см. seed_owner_optional_workout) — общий помощник и для «Full sweep» (#277)."""
    from app.db.models import ElectiveWorkout
    from app.domain.electives import ElectiveType
    from scripts.backfill_multi_program import (
        _ELECTIVE_EXERCISE_NAMES,
        _create_training_session_for_elective,
        _get_or_create_exercise,
    )

    now = datetime.now(UTC)
    for elective_type, at, sequence in (
        (ElectiveType.THREE_MINUTES, now - timedelta(minutes=30), [4, 3, 2]),
        (ElectiveType.MAX_REPS_LADDER, now - timedelta(minutes=90), [12, 10, 8, 6]),
    ):
        elective = ElectiveWorkout(
            user_id=user.id, elective_type=elective_type, performed_at=at, reps_sequence=sequence,
            total_reps=sum(sequence), equipment_type=EquipmentType.BAND, equipment_value=BAND_VALUE,
        )
        session.add(elective)
        await session.flush()
        exercise = await _get_or_create_exercise(
            session, name=_ELECTIVE_EXERCISE_NAMES[elective_type], subcategory=f"elective_{elective_type.value}",
        )
        await _create_training_session_for_elective(session, elective, exercise_id=exercise.id)
    await session.flush()


async def seed_journal_dedupe(session: AsyncSession, telegram_id: int) -> None:
    """#282/#284 — дубли в Журнале у мигрированного пользователя (скрыты backfill-копии, legacy — с действиями).

    Пользователь «до миграции» имеет три legacy Workout (две каскадные + одна, внесённая задним
    числом); backfill (scripts/backfill_multi_program.py, #163) переносит их в TrainingSession теми
    же функциями, что и в проде (`_create_training_session_for_workout` + `_get_or_create_exercise`);
    ПОСЛЕ миграции пишется ещё одна legacy-тренировка (бот/legacy-эндпоинты не пишут в v2) — она
    существует только в legacy и обязана остаться видна. Время — минуты назад, чтобы всё лежало в
    текущем месяце. Объёмы (макс. блока A) различаются: 11/12/13 — перенесённые, 14 — после миграции.
    Не backfill_all(): он обошёл бы всех онбордившихся пользователей общей БД."""
    from scripts.backfill_multi_program import (
        _EXERCISE_BLOCK_A_NAME,
        _EXERCISE_BLOCK_B_NAME,
        _create_training_session_for_workout,
        _get_or_create_exercise,
    )

    user = await UserRepository(session).create(telegram_id=telegram_id, username="e2e")
    now = datetime.now(UTC)
    onboarding = OnboardingService(session)
    _baseline, workout_set, _user = await onboarding.record_baseline_and_start(
        user_id=user.id, performed_at=now - timedelta(hours=2), reps=10,
    )
    await onboarding.complete_questionnaire_and_start_trial(user_id=user.id, now=now, **_QUESTIONNAIRE_DEFAULTS)
    repo = WorkoutRepository(session)

    async def legacy(minutes_ago: int, max_a: int, *, backdated: bool = False):
        kwargs = {
            "user_id": user.id, "workout_set_id": workout_set.id,
            "performed_at": now - timedelta(minutes=minutes_ago),
            "block_a_reps": BlockLog(working_reps=(10, 10, 10), max_reps=max_a),
            "block_b_reps": BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            "block_a_equipment_type": EquipmentType.BAND, "block_a_equipment_value": BAND_VALUE,
            "block_b_equipment_type": EquipmentType.BAND, "block_b_equipment_value": BAND_VALUE,
        }
        if backdated:
            return await repo.record_backdated_workout(**kwargs)
        return await repo.record_workout(**kwargs)

    await legacy(90, 11)
    await legacy(80, 12)
    await legacy(70, 13, backdated=True)
    await session.flush()

    # --- «миграция»: ровно то, что backfill делает для этого пользователя ---
    exercise_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    exercise_b = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_B_NAME, subcategory="block_b")
    for workout in await repo.list_for_user(user.id):
        await _create_training_session_for_workout(
            session, workout, exercise_a_id=exercise_a.id, exercise_b_id=exercise_b.id,
        )
    await session.flush()

    # --- после миграции: только legacy ---
    await legacy(20, 14)
    await session.flush()


SCENARIOS = {
    "sweep_empty": seed_sweep_empty,
    "sweep_populated": seed_sweep_populated,
    "sweep_defects": seed_sweep_defects,
    "journal_dedupe": seed_journal_dedupe,
    "collections": seed_collections_scenario,
    "owner_optional_workout": seed_owner_optional_workout,
    "analytics_distribution": seed_analytics_distribution,
    "body_metrics": seed_body_metrics,
    "background_interval": seed_background_interval,
    "session_recovery": seed_session_recovery,
    "golden_journey": seed_golden_journey,
    "home_workouts": seed_home_workouts,
    "home_discovery": seed_home_discovery,
    "workout_detail": seed_workout_detail,
    "analytics_v2": seed_analytics_v2,
    "analytics_metric": seed_analytics_metric,
    "tests_hub": seed_tests_hub,
    "peer_cohort_female": seed_peer_cohort_female,
    "peer_cohort_male": seed_peer_cohort_male,
    "peer_insufficient": seed_peer_insufficient,
    "peer_empty": seed_peer_empty,
    "journal_v2": seed_journal_v2,
    "journal_calendar": seed_journal_calendar,
    "journal_return": seed_journal_return,
    "journal_edit": seed_journal_edit,
    "journal_plans_polish": seed_journal_plans_polish,
    "builder_workouts": seed_builder_workouts,
    "not_onboarded": seed_not_onboarded,
    "first_workout": seed_first_workout,
    "ready": seed_ready,
    "v2_session_ready": seed_v2_session_ready,
    "v2_session_complex": seed_v2_session_complex,
    "v2_session_progression_edit": seed_v2_session_progression_edit,
    "plan_week_ready": seed_plan_week_ready,
    "plan_week_grouping": seed_plan_week_grouping,
    "plan_week_add_exercise": seed_plan_week_add_exercise,
    "plan_week_start_session": seed_plan_week_start_session,
    "plan_week_manual_session": seed_plan_week_manual_session,
    "journal_combined": seed_journal_combined,
    "plan_week_stepper": seed_plan_week_stepper,
    "plans_overview": seed_plans_overview,
}


async def _purge_dependents(session: AsyncSession, table, pks: list, seen: set) -> None:
    """Рекурсивно удаляет строки всех таблиц, ссылающихся FK на `table`
    (по метаданным моделей), у которых ссылка попадает в `pks`. Только для
    тестовых пользователей E2E-сида."""
    for child in Base.metadata.sorted_tables:
        for fk in child.foreign_keys:
            if fk.column.table is not table or (child.name, fk.parent.name) in seen:
                continue
            seen.add((child.name, fk.parent.name))
            pk_col = next(iter(child.primary_key.columns))
            rows = (await session.execute(select(pk_col).where(fk.parent.in_(pks)))).scalars().all()
            if rows:
                await _purge_dependents(session, child, list(rows), seen)
                await session.execute(delete(child).where(pk_col.in_(rows)))


async def _purge_user(session: AsyncSession, user_id: int) -> None:
    users = User.__table__
    await _purge_dependents(session, users, [user_id], set())
    await session.execute(delete(users).where(users.c.id == user_id))
    await session.flush()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("telegram_id", type=int)
    args = parser.parse_args()

    async with async_session_factory() as session:
        existing = await UserRepository(session).get_by_telegram_id(args.telegram_id)
        if existing is not None:
            # Идемпотентность (delete-recreate): повторный прогон (локально
            # или перезапуск CI-шага на той же БД) стирает прошлые строки
            # этого тестового пользователя и сидирует заново — состояние
            # каждый раз детерминированное, без UNIQUE-падения.
            await _purge_user(session, existing.id)
        await SCENARIOS[args.scenario](session, args.telegram_id)
        await session.commit()
    print(f"готово: {args.scenario} -> telegram_id={args.telegram_id}")


if __name__ == "__main__":
    asyncio.run(main())
