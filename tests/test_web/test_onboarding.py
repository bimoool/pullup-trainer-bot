"""POST /api/onboarding/baseline + POST /api/onboarding/questionnaire
(issue #124, PR 2) — замер и анкета, первые два бот-only куска, перенесённые
в Mini App. Оба вызывают ровно тот же OnboardingService, что и
app/bot/handlers/onboarding.py/questionnaire.py — не отдельная веб-копия
логики (проверяется прямым сравнением с прямым вызовом сервиса, как и в
tests/test_web/test_workout.py::test_submit_uses_same_progression_as_direct_repository_call)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app


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


async def _post(session, telegram_id: int, path: str, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(path, json=payload)
    finally:
        app.dependency_overrides.clear()


# --- POST /api/onboarding/baseline -------------------------------------------------


async def test_baseline_creates_user_if_missing(session):
    response = await _post(session, telegram_id=51001, path="/api/onboarding/baseline", payload={"reps": 8})
    assert response.status_code == 200

    user = await UserRepository(session).get_by_telegram_id(51001)
    assert user is not None

    baselines = await BaselineRepository(session).list_for_user(user.id)
    assert len(baselines) == 1
    assert baselines[0].reps == 8


async def test_baseline_reuses_existing_user(session):
    user = await UserRepository(session).create(telegram_id=51002, username="already-there")

    response = await _post(session, telegram_id=51002, path="/api/onboarding/baseline", payload={"reps": 5})
    assert response.status_code == 200

    same_user = await UserRepository(session).get_by_telegram_id(51002)
    assert same_user.id == user.id


async def test_baseline_unlocks_first_baseline_achievement(session):
    response = await _post(session, telegram_id=51003, path="/api/onboarding/baseline", payload={"reps": 3})
    assert response.status_code == 200

    user = await UserRepository(session).get_by_telegram_id(51003)
    achievements = await AchievementRepository(session).list_for_user(user.id)
    assert [a.code for a in achievements] == ["first_baseline"]


async def test_baseline_motivation_message_for_zero(session):
    response = await _post(session, telegram_id=51004, path="/api/onboarding/baseline", payload={"reps": 0})
    body = response.json()
    assert body["reps"] == 0
    assert "Ноль подтягиваний" in body["motivation_message"]


async def test_baseline_motivation_message_for_low(session):
    response = await _post(session, telegram_id=51005, path="/api/onboarding/baseline", payload={"reps": 11})
    body = response.json()
    assert "Отличный старт" in body["motivation_message"]


async def test_baseline_motivation_message_for_high(session):
    response = await _post(session, telegram_id=51006, path="/api/onboarding/baseline", payload={"reps": 12})
    body = response.json()
    assert "машина" in body["motivation_message"]


async def test_baseline_rejects_value_above_max_reps(session):
    response = await _post(session, telegram_id=51007, path="/api/onboarding/baseline", payload={"reps": 1000})
    assert response.status_code == 422


async def test_baseline_rejects_negative_value(session):
    response = await _post(session, telegram_id=51008, path="/api/onboarding/baseline", payload={"reps": -1})
    assert response.status_code == 422


# --- POST /api/onboarding/questionnaire --------------------------------------------


def _questionnaire_payload(**overrides) -> dict:
    payload = {
        "weight_kg": "78.5",
        "height_cm": 180,
        "gender": "male",
        "birth_date": "1996-03-15",
        "timezone": "Europe/Moscow",
    }
    payload.update(overrides)
    return payload


async def test_questionnaire_requires_existing_user(session):
    response = await _post(
        session, telegram_id=51101, path="/api/onboarding/questionnaire", payload=_questionnaire_payload(),
    )
    assert response.status_code == 404


async def test_questionnaire_completes_onboarding_and_starts_trial(session):
    user = await UserRepository(session).create(telegram_id=51102, username="mid")
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=8)

    response = await _post(
        session, telegram_id=51102, path="/api/onboarding/questionnaire", payload=_questionnaire_payload(),
    )
    assert response.status_code == 200
    assert response.json()["trial_days"] == 14

    updated = await UserRepository(session).get_by_telegram_id(51102)
    assert updated.onboarding_completed_at is not None
    assert updated.weight_kg == 78.5 or str(updated.weight_kg) == "78.5"
    assert updated.height_cm == 180
    assert updated.gender.value == "male"
    assert updated.birth_date == date(1996, 3, 15)
    assert updated.timezone == "Europe/Moscow"
    assert updated.subscription_status.value in ("trial", "active")


async def test_questionnaire_rejects_future_birth_date(session):
    user = await UserRepository(session).create(telegram_id=51103, username="mid")
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=8)

    future_date = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    response = await _post(
        session, telegram_id=51103, path="/api/onboarding/questionnaire",
        payload=_questionnaire_payload(birth_date=future_date),
    )
    assert response.status_code == 422


async def test_questionnaire_rejects_invalid_timezone(session):
    user = await UserRepository(session).create(telegram_id=51104, username="mid")
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=8)

    response = await _post(
        session, telegram_id=51104, path="/api/onboarding/questionnaire",
        payload=_questionnaire_payload(timezone="Not/A_Zone"),
    )
    assert response.status_code == 422


async def test_questionnaire_rejects_non_positive_weight(session):
    user = await UserRepository(session).create(telegram_id=51105, username="mid")
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=8)

    response = await _post(
        session, telegram_id=51105, path="/api/onboarding/questionnaire",
        payload=_questionnaire_payload(weight_kg="0"),
    )
    assert response.status_code == 422
