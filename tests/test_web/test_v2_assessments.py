"""/api/v2/assessments — хаб «Тесты» (#260)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import Baseline, User
from app.db.models_program import AssessmentResult, TrainingSession
from app.db.repositories.users import UserRepository
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch, v2_post

BASE = "/api/v2/assessments"


def _day(offset: int = 0) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


async def _protocols(session, user: User) -> dict[str, dict]:
    response = await v2_get(session, user.telegram_id, BASE)
    assert response.status_code == 200
    return {p["name"]: p for p in response.json()["protocols"]}


async def _record(session, user: User, protocol_id: int, value, day: str, note=None):
    return await v2_post(
        session, user.telegram_id, f"{BASE}/{protocol_id}/results",
        {"performed_on": day, "value": value, "note": note},
    )


async def test_seeded_protocols_listed_without_results(session, user: User):
    protocols = await _protocols(session, user)
    assert {"Максимум подтягиваний", "Вис на перекладине, сек", "Подтягивания с весом, кг"} <= protocols.keys()
    pullups = protocols["Максимум подтягиваний"]
    assert (pullups["metric_type"], pullups["unit"]) == ("reps", "повт.")
    assert protocols["Вис на перекладине, сек"]["unit"] == "сек"
    assert protocols["Подтягивания с весом, кг"]["unit"] == "кг"
    assert pullups["last_result"] is None and pullups["results_count"] == 0 and pullups["trend"] == []
    assert pullups["description"]


async def test_record_lists_last_result_trend_and_history_newest_first(session, user: User):
    pid = (await _protocols(session, user))["Максимум подтягиваний"]["id"]
    for value, offset in ((10, -20), (12, -10), (11, -1)):
        assert (await _record(session, user, pid, value, _day(offset))).status_code == 201

    protocol = (await _protocols(session, user))["Максимум подтягиваний"]
    assert protocol["results_count"] == 3
    assert protocol["last_result"]["value"] == "11" and protocol["last_result"]["performed_on"] == _day(-1)
    assert protocol["trend"] == ["10", "12", "11"]  # от старых к новым

    detail = (await v2_get(session, user.telegram_id, f"{BASE}/{pid}/results")).json()
    assert [r["value"] for r in detail["results"]] == ["11", "12", "10"]
    assert detail["protocol"]["id"] == pid


async def test_create_validation(session, user: User):
    pid = (await _protocols(session, user))["Максимум подтягиваний"]["id"]
    assert (await _record(session, user, pid, 10, _day(2))).status_code == 422  # будущее
    assert (await _record(session, user, pid, 0, _day())).status_code == 422
    assert (await _record(session, user, pid, -3, _day())).status_code == 422
    assert (await _record(session, user, pid, 10000, _day())).status_code == 422
    assert (await _record(session, user, pid, 10.5, _day())).status_code == 422  # повторения — целые
    assert (await _record(session, user, pid, 10, _day(), "x" * 501)).status_code == 422
    assert (await _record(session, user, 999_999, 10, _day())).status_code == 404
    hang = (await _protocols(session, user))["Вис на перекладине, сек"]["id"]
    assert (await _record(session, user, hang, 42.5, _day(), "  с резиной  ")).status_code == 201
    stored = (await v2_get(session, user.telegram_id, f"{BASE}/{hang}/results")).json()["results"][0]
    assert (stored["value"], stored["note"]) == ("42.5", "с резиной")
    assert (await v2_get(session, user.telegram_id, f"{BASE}/999999/results")).status_code == 404


async def test_update_and_delete_own_result(session, user: User):
    pid = (await _protocols(session, user))["Максимум подтягиваний"]["id"]
    created = (await _record(session, user, pid, 10, _day(-5), "старая")).json()

    patched = await v2_patch(
        session, user.telegram_id, f"{BASE}/results/{created['id']}",
        {"value": 13, "performed_on": _day(-2), "note": None},
    )
    assert patched.status_code == 200
    assert (patched.json()["value"], patched.json()["performed_on"], patched.json()["note"]) == ("13", _day(-2), None)

    assert (await v2_patch(session, user.telegram_id, f"{BASE}/results/{created['id']}", {"performed_on": _day(2)})
            ).status_code == 422
    assert (await v2_patch(session, user.telegram_id, f"{BASE}/results/{created['id']}", {"value": 0})
            ).status_code == 422
    assert (await v2_patch(session, user.telegram_id, f"{BASE}/results/{created['id']}", {"value": 12.5})
            ).status_code == 422

    assert (await v2_delete(session, user.telegram_id, f"{BASE}/results/{created['id']}")).status_code == 204
    assert (await v2_delete(session, user.telegram_id, f"{BASE}/results/{created['id']}")).status_code == 404
    assert (await _protocols(session, user))["Максимум подтягиваний"]["results_count"] == 0


async def test_foreign_results_are_404_and_untouched(session, user: User):
    other = await UserRepository(session).create(telegram_id=2002, username="other")
    pid = (await _protocols(session, user))["Максимум подтягиваний"]["id"]
    mine = (await _record(session, user, pid, 10, _day(-1))).json()

    assert (await v2_patch(session, other.telegram_id, f"{BASE}/results/{mine['id']}", {"value": 99})
            ).status_code == 404
    assert (await v2_delete(session, other.telegram_id, f"{BASE}/results/{mine['id']}")).status_code == 404

    row = (await session.execute(select(AssessmentResult).where(AssessmentResult.id == mine["id"]))).scalar_one()
    assert str(row.value) == "10.00"
    # чужой пользователь не видит ничьих замеров
    assert (await _protocols(session, other))["Максимум подтягиваний"]["results_count"] == 0
    detail = (await v2_get(session, other.telegram_id, f"{BASE}/{pid}/results")).json()
    assert detail["results"] == []


async def test_unknown_user_is_404(session):
    assert (await v2_get(session, 777_777, BASE)).status_code == 404


async def test_recording_does_not_touch_progression_or_baselines(session, user: User):
    async def counts() -> tuple[int, int]:
        baselines = (await session.execute(select(func.count()).select_from(Baseline))).scalar_one()
        states = (await session.execute(select(func.count()).select_from(TrainingSession))).scalar_one()
        return baselines, states

    before = await counts()
    pid = (await _protocols(session, user))["Максимум подтягиваний"]["id"]
    created = (await _record(session, user, pid, 20, _day())).json()
    await v2_patch(session, user.telegram_id, f"{BASE}/results/{created['id']}", {"value": 21})
    await v2_delete(session, user.telegram_id, f"{BASE}/results/{created['id']}")
    assert await counts() == before
