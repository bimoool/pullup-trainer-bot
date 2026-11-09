"""New height collection is refused at every HTTP ingress; history is retained."""

from decimal import Decimal

from app.db.models import BodyMetric
from app.db.repositories.body_metrics import BodyMetricRepository
from tests.test_web.test_body_metrics import URL, _call


async def test_all_height_writes_are_refused_but_existing_history_remains(session, user):
    history = BodyMetricRepository(session)
    entry = await history.add(user.id, BodyMetric.HEIGHT_CM, Decimal(180))
    for method, path, payload in (
        ("PUT", "/api/profile", {"height_cm": 181}),
        ("POST", URL, {"metric": "height_cm", "value": "181"}),
        ("PATCH", f"{URL}/{entry.id}", {"value": "181"}),
    ):
        response = await _call(session, user.telegram_id, method, path, payload)
        assert response.status_code == 409
        await session.refresh(user)
        await session.refresh(entry)
        assert user.height_cm == 180 and entry.value == Decimal(180)
    response = await _call(session, user.telegram_id, "GET", f"{URL}?metric=height_cm")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert Decimal(response.json()["items"][0]["value"]) == Decimal(180)


async def test_old_profile_client_can_roundtrip_unchanged_height_without_collecting_it(session, user):
    history = BodyMetricRepository(session)
    await history.add(user.id, BodyMetric.HEIGHT_CM, Decimal(180))
    response = await _call(session, user.telegram_id, "PUT", "/api/profile", {
        "height_cm": 180, "timezone": "Asia/Yekaterinburg",
    })
    assert response.status_code == 200
    await session.refresh(user)
    assert user.height_cm == 180 and user.timezone == "Asia/Yekaterinburg"
    assert len(await history.list_for_user(user.id, BodyMetric.HEIGHT_CM)) == 1
