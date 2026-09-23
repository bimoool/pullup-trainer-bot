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
from tests.test_web._v2_client import v2_get, v2_post


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


# ============================================================================
# Phase C1 (issue #188) — Exercise ownership foundation, security tests
# ============================================================================


async def _create_second_user(session, telegram_id: int) -> User:
    """Второй, независимый пользователь для isolation-тестов — user из
    conftest.py фикстуры один, для User A/User B нужен ещё один."""
    from app.db.repositories.users import UserRepository

    users = UserRepository(session)
    second_user = await users.create(telegram_id=telegram_id, username="second_user")
    return second_user


async def test_user_sees_system_and_own_exercises_not_others(session, user: User):
    """User A видит все system Exercise и свои user Exercise, не видит
    user Exercise другого пользователя (User B)."""
    await seed_exercise_library(session)
    user_b = await _create_second_user(session, telegram_id=980002)

    create_a = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Моё упражнение A"})
    assert create_a.status_code == 200
    create_b = await v2_post(session, telegram_id=user_b.telegram_id, path="/api/v2/exercises", payload={"name": "Моё упражнение B"})
    assert create_b.status_code == 200

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")
    names = {ex["name"] for ex in response.json()["exercises"]}

    assert "Планка" in names  # system, видно всем
    assert "Отжимания" in names  # system, видно всем
    assert "Моё упражнение A" in names  # своё
    assert "Моё упражнение B" not in names  # чужое — не должно течь


async def test_user_b_does_not_see_user_a_exercise_symmetric(session, user: User):
    """Симметричная проверка — User B видит своё и system, не видит User A."""
    await seed_exercise_library(session)
    user_b = await _create_second_user(session, telegram_id=980003)

    await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Упражнение пользователя A"})
    await v2_post(session, telegram_id=user_b.telegram_id, path="/api/v2/exercises", payload={"name": "Упражнение пользователя B"})

    response = await v2_get(session, telegram_id=user_b.telegram_id, path="/api/v2/exercises")
    names = {ex["name"] for ex in response.json()["exercises"]}

    assert "Планка" in names
    assert "Упражнение пользователя B" in names
    assert "Упражнение пользователя A" not in names


async def test_get_visible_exercise_for_user_returns_none_for_others_exercise(session, user: User):
    """Repository-уровень (get_visible_exercise_for_user) — чужой user
    Exercise даёт None, не объект (route-уровень конвертирует в 404, если
    detail route используется — сам route пока не существует, проверяем
    сам helper напрямую)."""
    from app.db.repositories.programs import ProgramRepository

    user_b = await _create_second_user(session, telegram_id=980004)
    create_b = await v2_post(session, telegram_id=user_b.telegram_id, path="/api/v2/exercises", payload={"name": "Приватное B"})
    exercise_b_id = create_b.json()["id"]

    repo = ProgramRepository(session)
    visible_to_owner = await repo.get_visible_exercise_for_user(exercise_b_id, user_b.id)
    visible_to_stranger = await repo.get_visible_exercise_for_user(exercise_b_id, user.id)

    assert visible_to_owner is not None
    assert visible_to_owner.name == "Приватное B"
    assert visible_to_stranger is None  # чужое — None, не объект


async def test_get_visible_exercise_for_user_allows_system_exercise_to_anyone(session, user: User):
    await seed_exercise_library(session)
    from sqlalchemy import select as sa_select

    result = await session.execute(sa_select(Exercise).where(Exercise.name == "Планка"))
    plank = result.scalar_one()

    from app.db.repositories.programs import ProgramRepository

    repo = ProgramRepository(session)
    visible = await repo.get_visible_exercise_for_user(plank.id, user.id)
    assert visible is not None  # system — видно любому


async def test_create_exercise_sets_correct_ownership(session, user: User):
    response = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Новое упражнение"})
    assert response.status_code == 200
    exercise_id = response.json()["id"]

    result = await session.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = result.scalar_one()
    assert exercise.source_type == "user"
    assert exercise.owner_user_id == user.id


async def test_create_exercise_duplicate_names_allowed_across_owners(session, user: User):
    """Дубликаты имён разрешены: system/user, user A/user B, user A/user A."""
    await seed_exercise_library(session)
    user_b = await _create_second_user(session, telegram_id=980005)

    r1 = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Подтягивания"})
    assert r1.status_code == 200  # совпадает с возможным system-именем — разрешено

    r2 = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Подтягивания"})
    assert r2.status_code == 200  # user A дважды одно и то же имя — разрешено

    r3 = await v2_post(session, telegram_id=user_b.telegram_id, path="/api/v2/exercises", payload={"name": "Подтягивания"})
    assert r3.status_code == 200  # user B то же имя, что user A — разрешено

    assert r1.json()["id"] != r2.json()["id"] != r3.json()["id"]


async def test_create_exercise_rejects_empty_name(session, user: User):
    response = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "   "})
    assert response.status_code == 422


async def test_create_exercise_trims_whitespace(session, user: User):
    response = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "  Приседания  "})
    assert response.status_code == 200
    assert response.json()["name"] == "Приседания"
