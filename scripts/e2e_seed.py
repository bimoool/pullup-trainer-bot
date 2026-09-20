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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models import Gender, User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    Program,
    ProgramItem,
    ProgressionStrategyProfile,
    TrainingPlan,
)
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import SessionBlockInput, SetLogInput
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

    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    session.add(PlanItem(training_plan_id=plan.id, complex_id=complex_.id, count_per_week=1))
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
        session.add(
            PlanItem(
                training_plan_id=plan.id, exercise_id=manual_exercise.id,
                count_per_week=2, day_of_week=None, program_inclusion_id=None,
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

    plank = (await session.execute(select(Exercise).where(Exercise.name == "Планка"))).scalar_one()
    pushups = (await session.execute(select(Exercise).where(Exercise.name == "Отжимания"))).scalar_one()

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


SCENARIOS = {
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
}


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
            # CI гоняет это против свежей БД (сервис postgres поднимается
            # заново на каждый workflow run) — здесь только защита от
            # повторного локального прогона на непустой БД, где повторная
            # запись того же telegram_id упала бы на UNIQUE-констрейнте.
            print(
                f"telegram_id={args.telegram_id} уже сидирован, пропускаю "
                "(нужна чистая БД для пересидирования)"
            )
            return
        await SCENARIOS[args.scenario](session, args.telegram_id)
        await session.commit()
    print(f"готово: {args.scenario} -> telegram_id={args.telegram_id}")


if __name__ == "__main__":
    asyncio.run(main())
