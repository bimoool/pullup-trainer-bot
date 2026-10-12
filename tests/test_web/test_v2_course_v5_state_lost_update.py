"""Lost update progression_state V5.6: конкурирующие записи одной инклюзии не теряют друг друга.

Писатели ``program_inclusions.progression_state`` курса — PUT /course/inputs, запись теста 1RM, завершение
основного занятия (прогрессия) и старт MAIN (масса тела во входы). Каждый делает read → modify → write
ЦЕЛОГО JSONB. Без общей сериализации запрос, прочитавший состояние до коммита конкурента, записывал
устаревший dict поверх: исчезали тест 1RM и E1RM (а с ним — правило 48 ч), входы или шаг прогрессии.

Сценарий каждого теста детерминирован, без sleep-таймингов: запрос A останавливается ПОСЛЕ чтения
состояния (Event), запрос B идёт до конца либо до ожидания блокировки строки (видно в pg_stat_activity),
затем A отпускается. Каждый запрос — своя сессия и транзакция (как app.web.db.get_session). С
исправлением (``TrainingPlanRepository.lock_inclusion``: FOR NO KEY UPDATE + перечитывание) B ждёт A
либо A перечитывает зафиксированное B — сохраняются оба изменения; откат исправления воспроизводит
потерю."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.models_program import ProgramInclusion, TrainingSession
from app.services import course_v5
from app.web import routes_v2_course
from app.web.main import app
from tests.test_web._v2_client import v2_post
from tests.test_web.test_v2_course_v5 import (
    CONFIRMED,
    VALID_TEST,
    _age_saved_tests,
    _main_occurrences,
    _transition_80,
    clock,  # noqa: F401 — фикстура часов старта
)
from tests.test_web.test_v2_live_session_concurrency import _per_request_sessions

PUT_INPUTS = {"volume_capacity": 40}


class _Pause:
    """Первый вызов module.name останавливается на входе: entered — дошёл (состояние уже прочитано),
    ждёт release. Остальные вызовы проходят без остановки."""

    def __init__(self, monkeypatch, module, name: str) -> None:
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        original, used = getattr(module, name), []

        async def paused(*args, **kwargs):
            if not used:
                used.append(True)
                self.entered.set()
                await asyncio.wait_for(self.release.wait(), timeout=10)
            return await original(*args, **kwargs)

        monkeypatch.setattr(module, name, paused)


async def _done_or_waiting_on_lock(task: asyncio.Task, engine) -> None:
    """Ждём, пока конкурент B закончится или встанет в ожидание блокировки строки (детерминированное
    условие по pg_stat_activity, а не время)."""
    async with engine.connect() as probe:
        for _ in range(1000):
            if task.done():
                return
            waiting = await probe.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()",
                )
            )
            if waiting:
                return
            await probe.rollback()
            await asyncio.sleep(0.01)
    raise AssertionError("конкурент не завершился и не ждёт блокировку")


async def _race(engine, first, second) -> tuple:
    """first() останавливается на паузе после чтения; second() идёт до конца/блокировки; затем first
    отпускается. Возвращает ответы (first, second)."""
    pause = first.pause
    first_task = asyncio.create_task(first())
    await asyncio.wait_for(pause.entered.wait(), timeout=10)
    second_task = asyncio.create_task(second())
    await _done_or_waiting_on_lock(second_task, engine)
    pause.release.set()
    return await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=20)


async def _stored(engine, inclusion_id: int) -> ProgramInclusion:
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as fresh:
        return await fresh.scalar(
            select(ProgramInclusion).where(ProgramInclusion.id == inclusion_id)
        )


def _client():
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    )


def _call(client, method: str, path: str, payload: dict, pause: _Pause | None = None):
    async def run():
        return await getattr(client, method)(path, json=payload)

    run.pause = pause
    return run


def _assert_test_saved(state: dict, count: int = 1) -> None:
    assert len(state["one_rm_tests"]) == count, state["one_rm_tests"]
    assert state["inputs"]["e1rm_kg"] is not None


async def _assert_second_record_too_soon(
    client, record_path: str, engine, inclusion_id: int, count: int = 1
) -> None:
    """Сохранённый тест продолжает блокировать повтор раньше 48 ч."""
    again = await client.post(record_path, json={"attempts": VALID_TEST})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "one_rep_max_too_soon", (
        again.text
    )
    assert len((await _stored(engine, inclusion_id)).progression_state["one_rm_tests"]) == count


# --- record 1RM ↔ PUT /course/inputs --------------------------------------------------------------------------


@pytest.mark.parametrize("paused", ["put", "record"])
async def test_record_and_put_inputs_both_survive(
    session, user: User, test_dsn, monkeypatch, paused
):
    """paused=put — воспроизведение ревью: PUT прочитал состояние, тест 1RM записан и закоммичен, PUT
    дописывает своё. paused=record — обратный порядок: запись теста прочитала состояние, PUT пишет входы."""
    inclusion = await _transition_80(session, user)
    await session.commit()
    base = f"/api/v2/program-inclusions/{inclusion.id}/course"
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            if paused == "put":
                # PUT уже загрузил инклюзию (_require_course) и остановлен до update_inputs.
                put = _call(
                    c,
                    "put",
                    f"{base}/inputs",
                    PUT_INPUTS,
                    _Pause(monkeypatch, routes_v2_course, "update_inputs"),
                )
                put_response, record_response = await _race(
                    engine, put, _call(c, "post", f"{base}/one-rep-max", {"attempts": VALID_TEST})
                )
            else:
                # Запись теста под advisory-локом перечитала инклюзию и остановлена на проверке 48 ч.
                record = _call(
                    c,
                    "post",
                    f"{base}/one-rep-max",
                    {"attempts": VALID_TEST},
                    _Pause(monkeypatch, course_v5, "last_heavy_pulling_at"),
                )
                record_response, put_response = await _race(
                    engine, record, _call(c, "put", f"{base}/inputs", PUT_INPUTS)
                )
            assert (record_response.status_code, put_response.status_code) == (200, 200), (
                record_response.text,
                put_response.text,
            )

            state = (await _stored(engine, inclusion.id)).progression_state
            _assert_test_saved(state)
            assert state["inputs"]["volume_capacity"] == 40
            await _assert_second_record_too_soon(c, f"{base}/one-rep-max", engine, inclusion.id)
        await engine.dispose()


# --- record 1RM ↔ завершение MAIN ----------------------------------------------------------------------------


async def _started_main(session, user: User, inclusion: ProgramInclusion) -> int:
    """Курс с подтверждённым E1RM (первый тест 1RM трёхдневной давности — без него MAIN силы с весом не
    стартует) и начатое основное занятие с записанными подходами (по цели); старт сдвинут на 49 ч назад —
    следующий тест 1RM по правилу 48 ч уже допустим."""
    first = await v2_post(
        session,
        user.telegram_id,
        f"/api/v2/program-inclusions/{inclusion.id}/course/one-rep-max",
        {"attempts": VALID_TEST},
    )
    assert first.status_code == 200, first.text
    await _age_saved_tests(session, inclusion, hours=72)
    occurrence = (await _main_occurrences(session, user))[0]
    started = await v2_post(
        session,
        user.telegram_id,
        "/api/v2/sessions/live",
        {
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [occurrence["id"]],
        },
    )
    assert started.status_code == 200, started.text
    body = started.json()
    sets, index = [], 0
    for block_index, block in enumerate(body["blocks"]):
        for target in block["targets"]:
            sets.append(
                {
                    "set_index": index,
                    "exercise_id": block["exercise_id"],
                    "value": int(float(target["value"])),
                    "block_index": block_index,
                }
            )
            index += 1
    logged = await v2_post(
        session, user.telegram_id, f"/api/v2/sessions/live/{body['id']}/sets:batch", {"sets": sets}
    )
    assert logged.status_code == 200, logged.text
    at = datetime.now(UTC) - timedelta(hours=49)
    await session.execute(
        update(TrainingSession)
        .where(TrainingSession.id == body["id"])
        .values(performed_at=at, started_at=at)
    )
    await session.commit()
    return body["id"]


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize("paused", ["completion", "record"])
async def test_record_and_completion_both_survive(
    session, user: User, test_dsn, monkeypatch, paused
):
    inclusion = await _transition_80(session, user)
    session_id = await _started_main(session, user, inclusion)
    before = await _stored(session.bind, inclusion.id)
    base = f"/api/v2/program-inclusions/{inclusion.id}/course"
    complete_path = f"/api/v2/sessions/live/{session_id}/complete"
    complete_payload = {"abandoned": False, "block_checks": CONFIRMED}
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            if paused == "completion":
                # Прогрессия прочитала состояние (аргумент advance_session) и ждёт лестницу резин.
                complete = _call(
                    c,
                    "post",
                    complete_path,
                    complete_payload,
                    _Pause(monkeypatch, course_v5, "assistance_ladder"),
                )
                complete_response, record_response = await _race(
                    engine,
                    complete,
                    _call(c, "post", f"{base}/one-rep-max", {"attempts": VALID_TEST}),
                )
            else:
                record = _call(
                    c,
                    "post",
                    f"{base}/one-rep-max",
                    {"attempts": VALID_TEST},
                    _Pause(monkeypatch, course_v5, "last_heavy_pulling_at"),
                )
                record_response, complete_response = await _race(
                    engine, record, _call(c, "post", complete_path, complete_payload)
                )
            assert (record_response.status_code, complete_response.status_code) == (200, 200), (
                record_response.text,
                complete_response.text,
            )
            assert complete_response.json()["course_progression"] is not None

            stored = await _stored(engine, inclusion.id)
            state = stored.progression_state
            _assert_test_saved(state, count=2)
            # Шаг прогрессии не потерян: счётчик занятий, роль следующего занятия и ревизия — после MAIN.
            assert state["sessions_completed"] == before.progression_state["sessions_completed"] + 1
            assert state["next_role"] != before.progression_state["next_role"]
            assert stored.progression_state_rev == before.progression_state_rev + 1
            await _assert_second_record_too_soon(
                c, f"{base}/one-rep-max", engine, inclusion.id, count=2
            )
        await engine.dispose()


@pytest.mark.usefixtures("clock")
async def test_concurrent_duplicate_completion_progresses_once(
    session, user: User, test_dsn, monkeypatch
):
    """Две конкурентные «Завершить» одной сессии: первая держит строку сессии и инклюзии на шаге
    прогрессии, вторая ждёт и получает already_completed — ровно один шаг прогрессии."""
    inclusion = await _transition_80(session, user)
    session_id = await _started_main(session, user, inclusion)
    before = await _stored(session.bind, inclusion.id)
    path = f"/api/v2/sessions/live/{session_id}/complete"
    payload = {"abandoned": False, "block_checks": CONFIRMED}
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            first = _call(
                c, "post", path, payload, _Pause(monkeypatch, course_v5, "assistance_ladder")
            )
            responses = await _race(engine, first, _call(c, "post", path, payload))
        assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
        progressions = [r.json()["course_progression"] for r in responses]
        reasons = [r.json()["progression_skipped_reason"] for r in responses]
        assert (
            progressions[0] is not None
            and progressions[1] is None
            and reasons[1] == "already_completed"
        )
        stored = await _stored(engine, inclusion.id)
        assert (
            stored.progression_state["sessions_completed"]
            == before.progression_state["sessions_completed"] + 1
        )
        assert stored.progression_state_rev == before.progression_state_rev + 1
        assert stored.sequence_cursor == (before.sequence_cursor or 0) + (
            1 if before.sequence_cursor is not None else 0
        )
        await engine.dispose()
