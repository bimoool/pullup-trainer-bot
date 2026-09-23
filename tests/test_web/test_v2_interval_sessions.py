"""HTTP-level тесты Phase B1 interval workout (issue #215, gates 4/6/7) —
через реальный FastAPI ASGI-путь (tests.test_web._v2_client.v2_get/v2_post),
тот же паттерн, что tests/test_web/test_v2_sessions_journal.py уже
использует для Checkpoint 4C. Дополняет tests/test_services/
test_interval_workout_start.py (service-уровень) реальным API-контрактом
и multi-user изоляцией на уровне HTTP-эндпоинтов."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType
from tests.test_web._v2_client import v2_get, v2_post


async def _make_interval_plan_item(session: AsyncSession, user: User, *, title: str = "3 минуты подтягиваний") -> int:
    """Тот же decoy-паттерн, что tests/test_services/test_interval_workout_start.py
    (issue #215, gate 1) — заведомо другой Exercise на PlanItem.exercise_id,
    не совпадающий с настоящим упражнением внутри ComplexItem, чтобы тест
    не мог случайно пройти через старый exercise_id-path."""
    real_exercise = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="pull")
    session.add(real_exercise)
    decoy_exercise = Exercise(name="DECOY — не должно попасть в title/snapshot", metric_type=MetricType.REPS, category="decoy")
    session.add(decoy_exercise)
    await session.flush()

    workout = Complex(name=title, source_type="system")
    session.add(workout)
    await session.flush()

    protocol = {
        "type": "interval", "total_duration_seconds": 180,
        "work_seconds": 10, "rest_seconds": 20, "starts_with": "work",
    }
    session.add(ComplexItem(complex_id=workout.id, exercise_id=real_exercise.id, order_index=0, sets=0, protocol=protocol))
    await session.flush()

    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()

    plan_item = PlanItem(
        training_plan_id=plan.id, exercise_id=decoy_exercise.id, complex_id=workout.id,
        count_per_week=3, day_of_week=1,
    )
    session.add(plan_item)
    await session.flush()
    return plan_item.id


async def test_concrete_api_json_and_persisted_snapshot_result(session: AsyncSession):
    """Gate 6 — реальный serialized API contract, не описание словами."""
    users = UserRepository(session)
    user = await users.create(telegram_id=910001, username="api_proof")
    await users.complete_onboarding(user.id, datetime.now(UTC))
    plan_item_id = await _make_interval_plan_item(session, user)

    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_id]},
    )
    assert start.status_code == 200
    body = start.json()

    assert body["status"] == "started"
    assert "server_time" in body and body["server_time"] is not None
    assert body["interval"] is not None
    assert body["interval"]["phase"] == "get_ready"
    assert body["interval"]["total_duration_seconds"] == 180
    assert body["interval"]["work_seconds"] == 10
    assert body["interval"]["rest_seconds"] == 20
    assert "execution_started_at" in body["interval"]
    assert "total_end_at" in body["interval"]
    assert body["blocks"][0]["targets"] == []  # gate: ноль SetTarget
    assert "DECOY" not in str(body)  # decoy exercise_id нигде не просочился

    session_id = body["id"]

    # Persisted snapshot proof — читаем напрямую из БД.
    persisted = await session.get(TrainingSession, session_id)
    assert persisted.workout_snapshot is not None
    assert persisted.workout_snapshot["title"] == "3 минуты подтягиваний"
    assert persisted.workout_snapshot["items"][0]["exercise_name"] == "Подтягивания"
    assert "DECOY" not in str(persisted.workout_snapshot)


async def test_http_golden_journey_full_interval_lifecycle(session: AsyncSession):
    """Gate 7 — HTTP Golden Journey: Start → active (get_ready) → fake
    elapsed WORK → active → fake elapsed REST → active → fake beyond
    deadline → active возвращает None → sessions?status=completed
    показывает завершённую с полным result."""
    users = UserRepository(session)
    user = await users.create(telegram_id=910002, username="golden_journey")
    await users.complete_onboarding(user.id, datetime.now(UTC))
    plan_item_id = await _make_interval_plan_item(session, user)

    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_id]},
    )
    assert start.status_code == 200
    session_id = start.json()["id"]

    active1 = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")
    assert active1.status_code == 200
    assert active1.json()["session"]["interval"]["phase"] == "get_ready"

    # fake elapsed WORK: performed_at сдвинут на 8с назад (5с get_ready + 3с work)
    await session.execute(update(TrainingSession).where(TrainingSession.id == session_id).values(
        performed_at=datetime.now(UTC) - timedelta(seconds=8),
    ))
    await session.commit()
    active2 = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")
    assert active2.json()["session"]["interval"]["phase"] == "work"

    # fake elapsed REST: 5с get_ready + 10с work + 5с rest = 20с
    await session.execute(update(TrainingSession).where(TrainingSession.id == session_id).values(
        performed_at=datetime.now(UTC) - timedelta(seconds=20),
    ))
    await session.commit()
    active3 = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")
    assert active3.json()["session"]["interval"]["phase"] == "rest"

    # fake beyond deadline: 5с get_ready + 180с total + запас
    past = datetime.now(UTC) - timedelta(seconds=5 + 180 + 20)
    await session.execute(update(TrainingSession).where(TrainingSession.id == session_id).values(performed_at=past))
    await session.commit()
    active4 = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")
    assert active4.status_code == 200
    assert active4.json()["session"] is None  # не отдана как активная

    journal = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    assert journal.status_code == 200
    sessions = journal.json()["sessions"]
    matching = [s for s in sessions if s["id"] == session_id]
    assert len(matching) == 1
    entry = matching[0]
    assert entry["title"] == "3 минуты подтягиваний"
    assert entry["status"] == "completed"

    # Persisted result — полный контракт.
    from app.db.repositories.training_sessions import TrainingSessionRepository
    detail = await TrainingSessionRepository(session).get_for_user(session_id, user.id)
    result_json = detail.blocks[0].result
    assert result_json["type"] == "interval"
    assert result_json["planned_duration_seconds"] == 180
    assert result_json["actual_duration_seconds"] == 180
    assert result_json["completed_cycles"] == 6
    expected_deadline = past + timedelta(seconds=5 + 180)
    completed_at = datetime.fromisoformat(result_json["completed_at"])
    assert completed_at == expected_deadline  # gate (Кирилл) — точное равенство, не ±1с


async def test_list_sessions_user_isolation(session: AsyncSession):
    """Gate 4 — User A и User B оба имеют expired STARTED interval. User A
    вызывает GET /sessions?status=completed: финализируется ТОЛЬКО его
    сессия, User B не тронут, в response нет данных User B."""
    users = UserRepository(session)
    user_a = await users.create(telegram_id=910003, username="isolation_a")
    await users.complete_onboarding(user_a.id, datetime.now(UTC))
    user_b = await users.create(telegram_id=910004, username="isolation_b")
    await users.complete_onboarding(user_b.id, datetime.now(UTC))

    plan_item_a = await _make_interval_plan_item(session, user_a, title="Workout A")
    plan_item_b = await _make_interval_plan_item(session, user_b, title="Workout B")

    start_a = await v2_post(
        session, telegram_id=user_a.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_a]},
    )
    start_b = await v2_post(
        session, telegram_id=user_b.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_b]},
    )
    session_id_a, session_id_b = start_a.json()["id"], start_b.json()["id"]

    past = datetime.now(UTC) - timedelta(seconds=200)
    for sid in (session_id_a, session_id_b):
        await session.execute(update(TrainingSession).where(TrainingSession.id == sid).values(performed_at=past))
    await session.commit()

    # User A вызывает Журнал — должен финализировать ТОЛЬКО свою сессию.
    journal_a = await v2_get(session, telegram_id=user_a.telegram_id, path="/api/v2/sessions?status=completed")
    assert journal_a.status_code == 200
    ids_in_response = {s["id"] for s in journal_a.json()["sessions"]}
    assert session_id_a in ids_in_response
    assert session_id_b not in ids_in_response  # чужих данных в ответе нет

    from app.db.repositories.training_sessions import TrainingSessionRepository
    repo = TrainingSessionRepository(session)
    detail_a = await repo.get_for_user(session_id_a, user_a.id)
    assert detail_a.status.value == "completed"  # финализирована

    detail_b = await repo.get_for_user(session_id_b, user_b.id)
    assert detail_b.status.value == "started"  # НЕ тронута вызовом User A
    assert detail_b.blocks[0].result is None
