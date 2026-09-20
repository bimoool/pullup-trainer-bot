"""Тесты GET /api/v2/exercises (Checkpoint 3A, issue #196) — минимальная
Exercise Library без UI.

Integration review (issue #188): исходная версия этого файла (Worker A,
коммит 2b205d8) использовала несуществующие в проекте фикстуры
(test_client/authed_headers/session_maker) — ни разу не прогонялась самим
воркером (честно заявлено в PERMISSION DENIALS), падала на сборе тестов.
Переписано на реальный паттерн — tests/test_web/_v2_client.py::v2_get/
v2_post + фикстуры session/user (тот же, что tests/test_web/test_v2_plan.py
и остальные test_v2_*.py уже используют).

Required tests (из issue):
- GET /exercises возвращает существующие Exercise
- Планка присутствует
- Отжимания присутствуют
- Планка.metric_type == time
- Отжимания.metric_type == reps
- повторный seed не создаёт дублей
- endpoint не требует admin-доступа
"""

from sqlalchemy import func, select

from app.db.models import User
from app.db.models_program import Exercise
from app.domain.multi_program import MetricType
from scripts.seed_exercise_library import seed_exercise_library
from tests.test_web._v2_client import v2_get


async def test_list_exercises_returns_existing_exercises(session, user: User):
    await seed_exercise_library(session)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")

    assert response.status_code == 200
    data = response.json()
    assert "exercises" in data
    assert isinstance(data["exercises"], list)


async def test_plank_present_with_time_metric(session, user: User):
    await seed_exercise_library(session)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")
    exercises = response.json()["exercises"]

    plank = next((ex for ex in exercises if ex["name"] == "Планка"), None)
    assert plank is not None, "Планка должна присутствовать"
    assert plank["metric_type"] == "time", "Планка должна иметь metric_type=time"
    assert plank["category"] == "Общая физическая подготовка"
    assert plank["subcategory"] is None


async def test_pushups_present_with_reps_metric(session, user: User):
    await seed_exercise_library(session)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")
    exercises = response.json()["exercises"]

    pushups = next((ex for ex in exercises if ex["name"] == "Отжимания"), None)
    assert pushups is not None, "Отжимания должны присутствовать"
    assert pushups["metric_type"] == "reps", "Отжимания должны иметь metric_type=reps"
    assert pushups["category"] == "Общая физическая подготовка"
    assert pushups["subcategory"] is None


async def test_repeated_seed_does_not_create_duplicates(session):
    result1 = await seed_exercise_library(session)
    result2 = await seed_exercise_library(session)

    # Одинаковые id означают, что вторая попытка нашла уже существующие,
    # а не создала новые.
    assert result1["Планка"] == result2["Планка"]
    assert result1["Отжимания"] == result2["Отжимания"]

    count_plank = await session.execute(
        select(func.count()).select_from(Exercise).where(Exercise.name == "Планка"),
    )
    assert count_plank.scalar_one() == 1, "Должна быть ровно одна Планка"

    count_pushups = await session.execute(
        select(func.count()).select_from(Exercise).where(Exercise.name == "Отжимания"),
    )
    assert count_pushups.scalar_one() == 1, "Должны быть ровно одни Отжимания"


async def test_endpoint_does_not_require_admin_access(session, user: User):
    """user из conftest.py — обычный, не-admin пользователь."""
    await seed_exercise_library(session)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")

    assert response.status_code == 200, "Обычный пользователь должен иметь доступ"
    exercises = response.json()["exercises"]
    assert len(exercises) >= 2, "Должны быть доступны хотя бы 2 упражнения"


async def test_exercise_response_fields_match_model(session, user: User):
    """Response содержит только поля, реально существующие в Exercise model
    (не equipment/difficulty/duration/muscles)."""
    await seed_exercise_library(session)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")
    exercises = response.json()["exercises"]
    assert len(exercises) >= 1

    exercise = exercises[0]
    assert "id" in exercise
    assert "name" in exercise
    assert "metric_type" in exercise
    assert "category" in exercise
    assert "subcategory" in exercise

    assert "equipment" not in exercise
    assert "difficulty" not in exercise
    assert "duration" not in exercise
    assert "muscles" not in exercise


async def test_internal_step_role_exercises_are_excluded_from_library(session, user: User):
    """Product-contract gap, найден живым Playwright-прогоном Checkpoint 3
    (не в исходном issue #196): GET /exercises отдавал и Планку/Отжимания,
    и внутренние блоки программ (subcategory=block_a/block_b) — пользователь
    мог добавить чужой строительный блок как самостоятельное упражнение.

    Фильтр — по уже существующей конвенции, не новой: та же пара значений
    subcategory, которую ProgramRepository.find_step_role_exercises()
    использует для StepProgressionStrategy (подтверждено в issue #165)."""
    await seed_exercise_library(session)
    session.add_all([
        Exercise(name="Подтягивания — объём", metric_type=MetricType.REPS, category="pull_ups", subcategory="block_a"),
        Exercise(name="Подтягивания — сила", metric_type=MetricType.REPS, category="pull_ups", subcategory="block_b"),
    ])
    await session.flush()

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")
    names = {ex["name"] for ex in response.json()["exercises"]}

    assert "Планка" in names
    assert "Отжимания" in names
    assert "Подтягивания — объём" not in names
    assert "Подтягивания — сила" not in names
