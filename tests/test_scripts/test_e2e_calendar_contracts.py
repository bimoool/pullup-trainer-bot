"""Signed real-PostgreSQL oracles for the residual E2E calendar contracts."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.config import settings
from app.db.models_program import TrainingPlan, TrainingSession
from app.db.repositories.users import UserRepository
from app.services import program_inclusion
from app.web import routes, routes_v2
from app.web.db import get_session
from app.web.main import app
from scripts import e2e_seed
from scripts.backfill_multi_program import seed_catalog
from scripts.qa.mint_init_data import build_init_data
from tests.support.plan_calendar import frozen_datetime

TG = 997_509
TOKEN = "e2e-test-token"
MOSCOW = ZoneInfo("Europe/Moscow")
CLOCKS = [
    (datetime(2026, 11, 15, 20, 59, 59, tzinfo=UTC), 1),
    (datetime(2026, 11, 15, 21, tzinfo=UTC), 2),
    (datetime(2026, 11, 15, 23, 59, 59, tzinfo=UTC), 2),
    (datetime(2026, 11, 16, tzinfo=UTC), 1),
    (datetime(2027, 1, 31, 21, tzinfo=UTC), 2),
    (datetime(2028, 12, 31, 21, tzinfo=UTC), 2),
]


@pytest_asyncio.fixture
async def signed_client(session, monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)

    async def database():
        yield session

    app.dependency_overrides[get_session] = database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Telegram-Init-Data": build_init_data(TG, TOKEN)},
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def freeze(monkeypatch, now):
    monkeypatch.setattr(e2e_seed, "datetime", frozen_datetime(now))
    monkeypatch.setattr(routes, "datetime", frozen_datetime(now))
    monkeypatch.setattr(routes_v2, "datetime", frozen_datetime(now))
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
    monkeypatch.setattr(program_inclusion, "datetime", frozen_datetime(now))


def monday(day):
    return day - timedelta(days=day.weekday())


async def get_plan(client):
    response = await client.get("/api/v2/plan")
    assert response.status_code == 200, response.text
    return response.json()["plan"]


@pytest.mark.parametrize("now,expected_number", CLOCKS)
@pytest.mark.parametrize("scenario", ["plan_week_ready", "course_journey"])
async def test_current_and_relative_future_week_contracts(
    session, monkeypatch, signed_client, now, expected_number, scenario
):
    freeze(monkeypatch, now)

    def timestamp(mapper, connection, plan):
        if plan.created_at is None:
            plan.created_at = now

    event.listen(TrainingPlan, "before_insert", timestamp)
    try:
        if scenario == "plan_week_ready":
            await e2e_seed.seed_plan_week_ready(session, TG)
        else:
            user = await e2e_seed._onboard(session, TG)
            catalog = await seed_catalog(session)
            inclusion = await e2e_seed.ProgramInclusionService(session).create_inclusion(
                user_id=user.id,
                request=e2e_seed.ProgramInclusionRequest(
                    program_id=catalog.program_id, course_inputs=e2e_seed._V5_E2E_INPUTS
                ),
            )
            inclusion.started_at = now  # The timestamp PostgreSQL would store at the test instant.
        await session.commit()
    finally:
        event.remove(TrainingPlan, "before_insert", timestamp)
    plan = await get_plan(signed_client)
    current = next(w for w in plan["plan_weeks"] if w["id"] == plan["current_week_id"])
    local_today = now.astimezone(MOSCOW).date()
    assert plan["today"] == local_today.isoformat()
    assert current["week_number"] == expected_number
    assert current["start_date"] == monday(local_today).isoformat()
    assert current["phase"] == "base"
    items = [i for i in plan["plan_items"] if i["plan_week_id"] == current["id"]]
    inclusion = plan["program_inclusions"][0]
    assert all(i["program_inclusion_id"] == inclusion["id"] for i in items)
    if scenario == "plan_week_ready":
        assert len(plan["plan_weeks"]) == 1
        assert len(items) == len(plan["plan_items"]) == 4
        assert sorted(i["day_of_week"] for i in items if i["day_of_week"] is not None) == [1]
        assert sum(i["day_of_week"] is None for i in items) == 3
        return
    assert len(items) == 2
    # This recurring course has no duration counter; its first local calendar week
    # still maps to the current PlanWeek (which can already be numbered 2).
    assert datetime.fromisoformat(inclusion["started_at"]).astimezone(MOSCOW).date() == local_today
    for offset in (1, 2):
        number = current["week_number"] + offset
        created = await signed_client.post("/api/v2/plan/weeks", json={"week_number": number})
        assert created.status_code == 200, created.text
        # Repeated GET is the server side of reload; preserve row identities and targets.
        future_plan = await get_plan(signed_client)
        assert await get_plan(signed_client) == future_plan
        assert future_plan["current_week_id"] == current["id"]
        week = next(w for w in future_plan["plan_weeks"] if w["week_number"] == number)
        expected_start = monday(local_today) + timedelta(weeks=offset)
        assert week["start_date"] == expected_start.isoformat()
        started_local = datetime.fromisoformat(inclusion["started_at"]).astimezone(MOSCOW).date()
        assert (expected_start - monday(started_local)).days // 7 + 1 == offset + 1
        future = [i for i in future_plan["plan_items"] if i["plan_week_id"] == week["id"]]
        assert len(future) == 2
        assert all(
            i["program_inclusion_id"] == inclusion["id"] and i["count_per_week"] == 1
            for i in future
        )
        assert len({i["occurrence_index"] for i in future}) == 2
        assert all(i["state"] == "available" for i in future)
    row = future[0]
    start = await signed_client.post(
        "/api/v2/sessions/live",
        json={
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [row["id"]],
            "engine_version": 1,
        },
    )
    assert start.status_code == 200, start.text
    live = start.json()
    assert len(live["blocks"]) == 2
    assert all(block["targets"] for block in live["blocks"])
    assert all(
        target["value"] is not None for block in live["blocks"] for target in block["targets"]
    )
    stored = await session.get(TrainingSession, live["id"])
    assert stored.plan_item_id == row["id"]


@pytest.mark.parametrize(
    "midnight",
    [
        datetime(2026, 11, 16, tzinfo=UTC),
        datetime(2027, 2, 1, tzinfo=UTC),
        datetime(2029, 1, 1, tzinfo=UTC),
    ],
)
async def test_sweep_dates_only_preparation_preserves_two_facts_across_midnight(
    session, monkeypatch, signed_client, midnight
):
    seed_at = midnight - timedelta(minutes=49)  # Actual old CI: seed ~23:11, D2 ~00:22.
    freeze(monkeypatch, seed_at)
    await e2e_seed.seed_sweep_defects(session, TG)
    await session.commit()
    profile = await signed_client.get("/api/profile")
    assert profile.json()["days_since_last_workout"] == 2
    before = (await signed_client.get("/api/v2/sessions?status=completed&limit=25")).json()[
        "sessions"
    ]
    assert len(before) == 2
    for at, expected_age in [(midnight - timedelta(seconds=1), 2), (midnight, 3)]:
        freeze(monkeypatch, at)
        profile = (await signed_client.get("/api/profile")).json()
        assert profile["days_since_last_workout"] == expected_age
        assert profile["workouts_count"] == 2
    now = midnight + timedelta(minutes=22)
    freeze(monkeypatch, now)
    other = await UserRepository(session).create(telegram_id=997_599)
    for saved, days_ago in zip(before, (2, 5), strict=True):
        original = saved
        assert original["can_edit"] and original["source_v2"] == "manual_custom"
        assert [
            Decimal(log["value"]) for block in original["blocks"] for log in block["set_logs"]
        ] == [8, 7]
        # Deliberately show that this is ownership checked, even for a dates-only edit.
        foreign = await signed_client.patch(
            f"/api/v2/sessions/{saved['id']}",
            json={"performed_on": "2026-01-01"},
            headers={"X-Telegram-Init-Data": build_init_data(other.telegram_id, TOKEN)},
        )
        assert foreign.status_code == 404
        performed = datetime.fromisoformat(saved["performed_at"])
        target = performed + (now.date() - performed.date()) - timedelta(days=days_ago)
        response = await signed_client.patch(
            f"/api/v2/sessions/{saved['id']}",
            json={"performed_on": target.astimezone(MOSCOW).date().isoformat()},
        )
        assert response.status_code == 200, response.text
        updated = response.json()
        assert updated["id"] == original["id"]
        assert updated["blocks"] == original["blocks"]
        assert updated["source"] == original["source"] == "backdated"
        assert updated["status"] == original["status"] == "completed"
        assert (
            now.date() - datetime.fromisoformat(updated["performed_at"]).date()
        ).days == days_ago
    after = (await signed_client.get("/api/v2/sessions?status=completed&limit=25")).json()[
        "sessions"
    ]
    assert sorted(i["id"] for i in after) == sorted(i["id"] for i in before)
    profile = (await signed_client.get("/api/profile")).json()
    assert profile["days_since_last_workout"] == 2
    assert profile["workouts_count"] == 2
