"""GET/PUT/DELETE /api/workout/draft (issue #61) — черновик тренировки в
реальном времени: промежуточные результаты уже завершённых подходов
сохраняются на сервере по ходу тренировки, переживают закрытие Telegram
посреди неё (в отличие от исходного поведения волны 2 issue #59, где всё
держалось только в памяти браузера до финального submit).

test_submit_deletes_draft_on_success доказывает главное свойство: успешная
запись тренировки не оставляет черновик висеть — иначе следующий заход на
LiveWorkoutScreen ошибочно предложил бы восстановить уже сданную
тренировку."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_drafts import WorkoutDraftRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app

BAND_VALUE = Decimal("15.0")


@dataclass
class _FakeWebAppUser:
    id: int
    first_name: str


@dataclass
class _FakeInitData:
    user: _FakeWebAppUser


def _override_dependencies(session, telegram_id: int) -> None:
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def _request(
    session, telegram_id: int, method: str, path: str, json: dict | None = None,
):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.clear()


async def _request_ok(session, telegram_id: int, method: str, path: str, json: dict | None = None) -> dict:
    response = await _request(session, telegram_id, method, path, json)
    assert response.status_code == 200, response.text
    return response.json()


async def _make_returning_user(session, *, telegram_id: int, days_ago: int = 5) -> User:
    """Тот же приём, что tests/test_web/test_workout.py::_make_returning_user
    — снаряд уже известен для обоих блоков, needs_new_equipment=False,
    статус плана "ready"."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)

    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=days_ago),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    return user


async def test_get_draft_for_unknown_telegram_id_is_inactive(session):
    body = await _request_ok(session, 61101, "GET", "/api/workout/draft")
    assert body["active"] is False


async def test_get_draft_without_saved_draft_is_inactive(session, user: User):
    body = await _request_ok(session, user.telegram_id, "GET", "/api/workout/draft")
    assert body["active"] is False


async def test_put_draft_for_unknown_telegram_id_returns_404(session):
    response = await _request(
        session, 61102, "PUT", "/api/workout/draft",
        json={
            "step_index": 0, "block_a_working_reps": [], "block_a_max_reps": None,
            "block_b_working_reps": [], "block_b_max_reps": None,
        },
    )
    assert response.status_code == 404


async def test_put_draft_then_get_returns_saved_progress(session, user: User):
    put_body = await _request_ok(
        session, user.telegram_id, "PUT", "/api/workout/draft",
        json={
            "step_index": 2, "block_a_working_reps": [8, 9], "block_a_max_reps": None,
            "block_b_working_reps": [], "block_b_max_reps": None,
            "comment": "тест",
        },
    )
    assert put_body["active"] is True
    assert put_body["step_index"] == 2
    assert put_body["block_a_working_reps"] == [8, 9]
    assert put_body["comment"] == "тест"

    get_body = await _request_ok(session, user.telegram_id, "GET", "/api/workout/draft")
    assert get_body["active"] is True
    assert get_body["step_index"] == 2
    assert get_body["block_a_working_reps"] == [8, 9]
    assert get_body["comment"] == "тест"


async def test_put_draft_replaces_previous_draft(session, user: User):
    await _request_ok(
        session, user.telegram_id, "PUT", "/api/workout/draft",
        json={
            "step_index": 1, "block_a_working_reps": [8], "block_a_max_reps": None,
            "block_b_working_reps": [], "block_b_max_reps": None,
        },
    )

    body = await _request_ok(
        session, user.telegram_id, "PUT", "/api/workout/draft",
        json={
            "step_index": 5, "block_a_working_reps": [8, 9, 10], "block_a_max_reps": 12,
            "block_b_working_reps": [], "block_b_max_reps": None,
        },
    )

    assert body["step_index"] == 5
    assert body["block_a_working_reps"] == [8, 9, 10]
    assert body["block_a_max_reps"] == 12


async def test_delete_draft_removes_it(session, user: User):
    await _request_ok(
        session, user.telegram_id, "PUT", "/api/workout/draft",
        json={
            "step_index": 1, "block_a_working_reps": [8], "block_a_max_reps": None,
            "block_b_working_reps": [], "block_b_max_reps": None,
        },
    )

    delete_body = await _request_ok(session, user.telegram_id, "DELETE", "/api/workout/draft")
    assert delete_body["active"] is False

    get_body = await _request_ok(session, user.telegram_id, "GET", "/api/workout/draft")
    assert get_body["active"] is False


async def test_delete_draft_is_idempotent_without_draft(session, user: User):
    body = await _request_ok(session, user.telegram_id, "DELETE", "/api/workout/draft")
    assert body["active"] is False


async def test_delete_draft_for_unknown_telegram_id_is_ok(session):
    body = await _request_ok(session, 61103, "DELETE", "/api/workout/draft")
    assert body["active"] is False


async def test_drafts_are_scoped_per_user(session, user: User):
    other = await UserRepository(session).create(telegram_id=61104, username="other")
    await _request_ok(
        session, user.telegram_id, "PUT", "/api/workout/draft",
        json={
            "step_index": 1, "block_a_working_reps": [8], "block_a_max_reps": None,
            "block_b_working_reps": [], "block_b_max_reps": None,
        },
    )

    body = await _request_ok(session, other.telegram_id, "GET", "/api/workout/draft")
    assert body["active"] is False


async def test_submit_deletes_draft_on_success(session):
    user = await _make_returning_user(session, telegram_id=61105)
    await WorkoutDraftRepository(session).save(
        user_id=user.id, step_index=9, block_a_working_reps=[10, 10, 10], block_a_max_reps=11,
        block_b_working_reps=[3, 3, 3, 3], block_b_max_reps=3, block_a_actual_weight=None,
        block_b_actual_weight=None, block_a_actual_band_item_id=None,
        block_b_actual_band_item_id=None, comment=None,
    )

    submit_response = await _request(
        session, user.telegram_id, "POST", "/api/workout/submit",
        json={
            "block_a_working_reps": [10, 10, 10], "block_a_max_reps": 11,
            "block_b_working_reps": [3, 3, 3, 3], "block_b_max_reps": 3,
            "comment": None, "confirm_anomalies": False,
        },
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["status"] == "ok"

    draft_body = await _request_ok(session, user.telegram_id, "GET", "/api/workout/draft")
    assert draft_body["active"] is False
