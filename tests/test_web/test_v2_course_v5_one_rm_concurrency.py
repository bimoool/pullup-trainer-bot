"""Review #318: две КОНКУРЕНТНЫЕ записи теста 1RM (двойной тап, два устройства) не обходят правило 48 ч.

Каждый запрос — своя сессия и своя транзакция (как app.web.db.get_session); оба входят в запись
одновременно (барьер). Без сериализации оба прошли бы проверку «предыдущего теста нет» и оба дописали бы
тест. С advisory-локом пользователя проигравший после лока перечитывает инклюзию, видит закоммиченный
тест победителя и получает 409 one_rep_max_too_soon; в БД ровно один тест."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.models_program import ProgramInclusion
from app.web import routes_v2_course
from app.web.main import app
from tests.test_web.test_v2_course_v5 import STOPPED_TEST, VALID_TEST, _transition_80
from tests.test_web.test_v2_live_session_concurrency import _per_request_sessions


def _gate_record(monkeypatch, parties: int = 2) -> None:
    original = routes_v2_course.record_one_rep_max
    barrier = asyncio.Barrier(parties)

    async def gated(*args, **kwargs):
        await asyncio.wait_for(barrier.wait(), timeout=10)
        return await original(*args, **kwargs)

    monkeypatch.setattr(routes_v2_course, "record_one_rep_max", gated)


@pytest.mark.parametrize(("first", "second"), [
    pytest.param({"attempts": VALID_TEST}, {"attempts": VALID_TEST}, id="two-completed"),
    pytest.param({"attempts": VALID_TEST}, {"attempts": STOPPED_TEST, "stopped": True}, id="completed-and-stopped"),
])
async def test_two_concurrent_one_rep_max_records_one_wins_one_409(
    session, user: User, test_dsn, monkeypatch, first, second,
):
    inclusion = await _transition_80(session, user)
    await session.commit()
    _gate_record(monkeypatch)
    path = f"/api/v2/program-inclusions/{inclusion.id}/course/one-rep-max"
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            responses = await asyncio.gather(c.post(path, json=first), c.post(path, json=second))
        codes = sorted(response.status_code for response in responses)
        assert codes == [200, 409], [response.text for response in responses]
        loser = next(response for response in responses if response.status_code == 409)
        assert loser.json()["detail"]["code"] == "one_rep_max_too_soon"
        async with async_sessionmaker(engine, class_=AsyncSession)() as fresh:
            state = await fresh.scalar(select(ProgramInclusion.progression_state).where(ProgramInclusion.id == inclusion.id))
        assert len(state["one_rm_tests"]) == 1
        await engine.dispose()
