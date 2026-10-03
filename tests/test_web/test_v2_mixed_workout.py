"""REBUILD-1, R1 — исполнение смешанной Builder-тренировки: цели из
prescription, замороженный снимок, ручной переход между блоками,
per-block interval-таймер, дубли упражнения. Через реальный HTTP-путь
(tests.test_web._v2_client), как остальные v2-тесты."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    SessionBlock,
    SessionStatus,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType
from tests.test_web._v2_client import v2_get, v2_post

REPS = {
    "type": "reps_sets", "rest_seconds": 30, "prescription": {"source": "static", "sets": 2, "reps": 8},
}
TIME = {
    "type": "time_sets", "rest_seconds": 20, "prescription": {"source": "static", "sets": 2, "duration_seconds": 30},
}
MAX = {"type": "max_effort", "rest_seconds": 0, "prescription": {"source": "static", "attempts": 2}}
INTERVAL = {
    "type": "interval", "total_duration_seconds": 60, "work_seconds": 10, "rest_seconds": 20,
    "starts_with": "work",
}


async def _user(session: AsyncSession, telegram_id: int) -> User:
    users = UserRepository(session)
    user = await users.create(telegram_id=telegram_id, username=f"u{telegram_id}")
    await users.complete_onboarding(user.id, datetime.now(UTC))
    return user


async def _exercise(session: AsyncSession, name: str, metric: MetricType = MetricType.REPS) -> Exercise:
    exercise = Exercise(name=name, metric_type=metric, category="test")
    session.add(exercise)
    await session.flush()
    return exercise


async def _workout_plan_item(
    session: AsyncSession, user: User, items: list[tuple[Exercise, dict | None]], *, title: str = "Смешанная",
    legacy_sets: int = 9,
) -> tuple[int, Complex]:
    """legacy_sets намеренно НЕ совпадает с prescription — тест не пройдёт
    через ComplexItem.sets, если тот снова станет источником целей."""
    workout = Complex(name=title, source_type="user", owner_user_id=user.id)
    session.add(workout)
    await session.flush()
    for index, (exercise, protocol) in enumerate(items):
        session.add(ComplexItem(
            complex_id=workout.id, exercise_id=exercise.id, order_index=index, sets=legacy_sets, protocol=protocol,
        ))
    plan = await session.scalar(select(TrainingPlan).where(TrainingPlan.user_id == user.id))
    if plan is None:
        plan = TrainingPlan(user_id=user.id)
        session.add(plan)
        await session.flush()
    plan_item = PlanItem(
        training_plan_id=plan.id, exercise_id=items[0][0].id, complex_id=workout.id, count_per_week=1, day_of_week=1,
    )
    session.add(plan_item)
    await session.flush()
    return plan_item.id, workout


async def _start(session: AsyncSession, user: User, plan_item_id: int) -> dict:
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_id]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _active(session: AsyncSession, user: User) -> dict | None:
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")
    assert response.status_code == 200
    return response.json()["session"]


async def _advance(session: AsyncSession, user: User, body: dict) -> dict:
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{body['id']}/phase/next",
        payload={"expected_phase_index": body["phase_index"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _log_set(session: AsyncSession, user: User, body: dict, *, set_index: int, value: str) -> dict:
    block = body["blocks"][body["current_block_index"]]
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{body['id']}/sets:batch",
        payload={"sets": [{
            "set_index": set_index, "exercise_id": block["exercise_id"], "value": value,
            "block_index": body["current_block_index"],
        }]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _run_standard_block(session: AsyncSession, user: User, body: dict, *, first_set_index: int, value: str) -> dict:
    """get_ready -> go -> лог -> (rest -> get_ready ->)... до конца блока.
    Возвращает состояние сессии сразу после последнего phase/next блока."""
    index = body["current_block_index"]
    sets_count = len(body["blocks"][index]["targets"])
    for i in range(sets_count):
        body = await _advance(session, user, body)  # get_ready -> go
        assert body["phase"]["name"] == "go"
        await _log_set(session, user, body, set_index=first_set_index + i, value=value)
        body = await _advance(session, user, body)  # go -> rest | граница блока | done
        if i < sets_count - 1:
            assert body["phase"]["name"] == "rest"
            body = await _advance(session, user, body)  # rest -> get_ready
    return body


async def _start_block(session: AsyncSession, user: User, body: dict, index: int) -> dict:
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{body['id']}/blocks/start",
        payload={"expected_block_index": index},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _backdate_block_start(session: AsyncSession, session_id: int, order_index: int, seconds: int) -> None:
    await session.execute(
        update(SessionBlock)
        .where(SessionBlock.session_id == session_id, SessionBlock.order_index == order_index)
        .values(started_at=datetime.now(UTC) - timedelta(seconds=seconds)),
    )
    await session.commit()


# --- Цели из prescription, замороженный снимок -----------------------------------------------


async def test_targets_come_from_protocol_prescription_not_legacy_sets(session: AsyncSession):
    user = await _user(session, 930001)
    pull, plank, push = (
        await _exercise(session, "Подтягивания"), await _exercise(session, "Планка", MetricType.TIME),
        await _exercise(session, "Отжимания"),
    )
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS), (plank, TIME), (push, MAX)])

    body = await _start(session, user, plan_item_id)
    reps, time_, max_ = body["blocks"]

    assert [(t["value"], t["unit"]) for t in reps["targets"]] == [("8.00", "reps")] * 2  # не 9 подходов legacy
    assert [(t["value"], t["unit"]) for t in time_["targets"]] == [("30.00", "s")] * 2
    assert len(max_["targets"]) == 2  # число попыток из prescription
    assert [b["protocol_type"] for b in body["blocks"]] == ["reps_sets", "time_sets", "max_effort"]
    assert [b["exercise_name"] for b in body["blocks"]] == ["Подтягивания", "Планка", "Отжимания"]
    assert body["awaiting_block_start"] is False


async def test_protocol_identity_comes_from_frozen_snapshot(session: AsyncSession):
    user = await _user(session, 930002)
    pull, plank = await _exercise(session, "Подтягивания"), await _exercise(session, "Планка", MetricType.TIME)
    plan_item_id, workout = await _workout_plan_item(session, user, [(pull, REPS), (plank, TIME)])
    body = await _start(session, user, plan_item_id)

    # Пользователь правит Workout ПОСЛЕ старта: протокол и упражнение блока 0.
    await session.execute(
        update(ComplexItem).where(ComplexItem.complex_id == workout.id, ComplexItem.order_index == 0)
        .values(protocol=MAX, exercise_id=plank.id),
    )
    await session.commit()

    active = await _active(session, user)
    assert [b["protocol_type"] for b in active["blocks"]] == ["reps_sets", "time_sets"]
    assert active["blocks"][0]["exercise_name"] == "Подтягивания"
    persisted = await session.get(TrainingSession, body["id"])
    assert persisted.workout_snapshot["items"][0]["protocol"]["type"] == "reps_sets"


async def test_legacy_protocol_none_keeps_old_behavior(session: AsyncSession):
    user = await _user(session, 930003)
    pull = await _exercise(session, "Подтягивания")
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, None)], legacy_sets=3)
    body = await _start(session, user, plan_item_id)

    assert len(body["blocks"][0]["targets"]) == 3
    assert body["blocks"][0]["protocol_type"] is None
    persisted = await session.get(TrainingSession, body["id"])
    assert persisted.workout_snapshot is None


# --- Смешанная тренировка: reps -> interval -> max ---------------------------------------------


async def test_mixed_workout_manual_transitions_and_only_final_block_completes(session: AsyncSession):
    user = await _user(session, 930004)
    pull, burpee, push = (
        await _exercise(session, "Подтягивания"), await _exercise(session, "Бёрпи"), await _exercise(session, "Отжимания"),
    )
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS), (burpee, INTERVAL), (push, MAX)])
    body = await _start(session, user, plan_item_id)
    session_id = body["id"]

    # Блок 0 (reps): конец обычного блока в середине ПРОДВИГАЕТ, но не завершает сессию.
    body = await _run_standard_block(session, user, body, first_set_index=0, value="8")
    assert body["status"] == "started"
    assert body["current_block_index"] == 1
    assert body["awaiting_block_start"] is True
    assert body["interval"] is None  # не начатый interval-блок не проецируется как активный

    # Пока следующий блок не начат, phase/next — no-op (никакого авто-старта).
    same = await _advance(session, user, body)
    assert same["phase_index"] == body["phase_index"] and same["awaiting_block_start"] is True

    # Явный "Начать" стартует блок; двойной клик — ровно один раз.
    started = await _start_block(session, user, body, 1)
    again = await _start_block(session, user, started, 1)
    assert started["awaiting_block_start"] is False
    assert started["interval"]["phase"] == "get_ready"
    assert again["blocks"][1]["started_at"] == started["blocks"][1]["started_at"]
    assert again["phase_index"] == started["phase_index"]

    # Устаревший expected_block_index — молча отдаёт текущее состояние.
    stale = await _start_block(session, user, started, 0)
    assert stale["current_block_index"] == 1 and stale["phase_index"] == started["phase_index"]

    # Interval истекает в СЕРЕДИНЕ: сессия продвигается к блоку 2, но не завершается.
    await _backdate_block_start(session, session_id, 1, 5 + 60 + 10)
    active = await _active(session, user)
    assert active["status"] == "started"
    assert active["current_block_index"] == 2
    assert active["awaiting_block_start"] is True
    assert active["interval"] is None
    interval_result = active["blocks"][1]["result"]
    assert interval_result["type"] == "interval" and interval_result["planned_duration_seconds"] == 60
    assert interval_result["completed_cycles"] == 2  # 60/(10+20)

    # Блок 2 (max) стартует вручную; финальный блок завершает фазовую машину.
    body = await _start_block(session, user, active, 2)
    body = await _run_standard_block(session, user, body, first_set_index=2, value="22")
    assert body["phase"]["name"] == "done" and body["status"] == "started"

    complete = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/complete",
        payload={"abandoned": False},
    )
    assert complete.status_code == 200
    final = complete.json()
    assert final["status"] == "completed"
    assert [len(b["set_logs"]) for b in final["blocks"]] == [2, 0, 2]


async def test_interval_expiry_in_middle_via_finish_endpoint_advances(session: AsyncSession):
    user = await _user(session, 930005)
    burpee, plank = await _exercise(session, "Бёрпи"), await _exercise(session, "Планка", MetricType.TIME)
    plan_item_id, _ = await _workout_plan_item(session, user, [(burpee, INTERVAL), (plank, TIME)])
    body = await _start(session, user, plan_item_id)
    assert body["interval"]["phase"] == "get_ready"  # блок 0 interval начат вместе с сессией

    # Дедлайн ещё не наступил: finish — no-op.
    early = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{body['id']}/blocks/finish",
        payload={"expected_block_index": 0},
    )
    assert early.json()["current_block_index"] == 0 and early.json()["status"] == "started"

    await session.execute(
        update(TrainingSession).where(TrainingSession.id == body["id"])
        .values(performed_at=datetime.now(UTC) - timedelta(seconds=5 + 60 + 5)),
    )
    await session.commit()
    finish = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{body['id']}/blocks/finish",
        payload={"expected_block_index": 0},
    )
    data = finish.json()
    assert data["status"] == "started"
    assert data["current_block_index"] == 1 and data["awaiting_block_start"] is True
    assert data["blocks"][0]["result"]["completed_cycles"] == 2

    # Повторный finish (двойной вызов клиента) идемпотентен.
    repeat = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{body['id']}/blocks/finish",
        payload={"expected_block_index": 0},
    )
    assert repeat.json()["current_block_index"] == 1


async def test_last_interval_block_deadline_completes_session(session: AsyncSession):
    user = await _user(session, 930006)
    pull, burpee = await _exercise(session, "Подтягивания"), await _exercise(session, "Бёрпи")
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS), (burpee, INTERVAL)])
    body = await _start(session, user, plan_item_id)
    body = await _run_standard_block(session, user, body, first_set_index=0, value="8")
    body = await _start_block(session, user, body, 1)
    await _backdate_block_start(session, body["id"], 1, 5 + 60 + 5)

    finish = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{body['id']}/blocks/finish",
        payload={"expected_block_index": 1},
    )
    assert finish.json()["status"] == "completed"
    assert finish.json()["blocks"][1]["result"]["planned_duration_seconds"] == 60
    assert await _active(session, user) is None


# --- Дубли упражнения ----------------------------------------------------------------------


async def test_set_logs_resolve_to_block_not_exercise_id(session: AsyncSession):
    user = await _user(session, 930007)
    pull, plank = await _exercise(session, "Подтягивания"), await _exercise(session, "Планка", MetricType.TIME)
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS), (plank, TIME), (pull, REPS)])
    body = await _start(session, user, plan_item_id)
    session_id = body["id"]

    # Явный block_index=2: подход второго "Подтягиваний" не попадает в блок 0.
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [{"set_index": 0, "exercise_id": pull.id, "value": "5", "block_index": 2}]},
    )
    assert response.status_code == 200
    logs = [b["set_logs"] for b in response.json()["blocks"]]
    assert [len(entries) for entries in logs] == [0, 0, 1]

    # Без block_index (старый клиент) — ТЕКУЩИЙ блок; после перехода к блоку 2 это блок 2.
    await session.execute(
        update(TrainingSession).where(TrainingSession.id == session_id).values(current_block_index=2),
    )
    await session.commit()
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [{"set_index": 1, "exercise_id": pull.id, "value": "6"}]},
    )
    assert [len(b["set_logs"]) for b in response.json()["blocks"]] == [0, 0, 2]

    # Индекс блока с другим упражнением — 404, а не запись в чужой блок.
    bad = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [{"set_index": 2, "exercise_id": pull.id, "value": "7", "block_index": 1}]},
    )
    assert bad.status_code == 404


async def test_builder_mixed_with_plain_plan_items_is_rejected(session: AsyncSession):
    user = await _user(session, 930008)
    pull = await _exercise(session, "Подтягивания")
    builder_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS)])
    plan = await session.scalar(select(TrainingPlan).where(TrainingPlan.user_id == user.id))
    plain = PlanItem(training_plan_id=plan.id, exercise_id=pull.id, count_per_week=1, day_of_week=2)
    session.add(plain)
    await session.flush()

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [builder_item_id, plain.id]},
    )
    assert response.status_code == 422
    assert await session.scalar(select(TrainingSession.id).where(TrainingSession.user_id == user.id)) is None


async def test_completed_status_only_after_explicit_complete(session: AsyncSession):
    user = await _user(session, 930009)
    pull = await _exercise(session, "Подтягивания")
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS)])
    body = await _start(session, user, plan_item_id)
    body = await _run_standard_block(session, user, body, first_set_index=0, value="8")
    persisted = await session.get(TrainingSession, body["id"])
    await session.refresh(persisted)
    assert persisted.status == SessionStatus.STARTED


async def test_legacy_multi_block_session_keeps_automatic_block_advance(session: AsyncSession):
    """STEP/legacy-комплекс без Builder-протокола: ручной "Начать" не вводится,
    следующий блок сразу get_ready, как до R1."""
    user = await _user(session, 930010)
    pull, push = await _exercise(session, "Подтягивания"), await _exercise(session, "Отжимания")
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, None), (push, None)], legacy_sets=1)
    body = await _start(session, user, plan_item_id)

    body = await _advance(session, user, body)  # get_ready -> go
    body = await _advance(session, user, body)  # go -> границa блока

    assert body["current_block_index"] == 1
    assert body["phase"]["name"] == "get_ready" and body["phase"]["ends_at"] is not None
    assert body["awaiting_block_start"] is False
