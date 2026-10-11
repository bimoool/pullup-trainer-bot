"""Программа V5.6 (#305) исполняется Live Engine v2 (#306): интеграционные пути на реальном Postgres.

* План: явный отдых рецепта (240/30 → 900 → 180, решение владельца #306 п. 5), подтверждения у обоих блоков,
  стоп-правило объёма B, минимум AMRAP p4 и потолок контрольного подхода — в плане движка.
* Подтверждения (V5.6 §11) — внутри движка ДО канонического завершения: последний подход → CONFIRM,
  ``confirm_blocks`` → complete_session #307 ровно один раз; «не знаю» завершает, но прибавку не даёт; пауза в
  отдыхе между подходами — серверный факт «отдых превышен».
* Стоп B (§6): ≤ 2 повторения или «техника нарушена» завершает только объём B; 900 с → сила по рецепту.
* Повтор/дубли/гонки: дубль события, повторный complete, подтверждение после завершения, последний подход
  вместе с выходом — одно завершение, сессия не возвращается в started, журнал событий воспроизводим."""

import uuid
from datetime import timedelta

from sqlalchemy import update

from app.db.models_program import TrainingSession
from app.db.repositories.session_events import SessionEventRepository
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.achievements import AchievementCode
from app.services.live_engine import LiveEngineService, from_ms
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_course_v5 import (  # noqa: F401 — clock — фикстура
    CONFIRMED,
    MON,
    _enrol,
    _main_occurrences,
    _pullups,
    clock,
)
from tests.test_web.test_v2_live_session_workout_start import _user

VALID = [
    {"block_index": 0, "technique": "valid", "rest": "valid"},
    {"block_index": 1, "technique": "valid", "rest": "valid"},
]

LIVE = "/api/v2/sessions/live"
WEIGHTED_INPUTS = {"e1rm_kg": "30", "load_step_kg": "0.5"}


async def _start(session, user, plan_item_id: int) -> dict:
    response = await v2_post(session, user.telegram_id, LIVE, {
        "client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_id], "engine_version": 2,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine_version"] == 2
    return body


async def _event(session, user, session_id: int, type_: str, payload: dict) -> dict:
    return await _events(session, user, session_id, [{"client_event_id": str(uuid.uuid4()), "type": type_, "payload": payload}])


async def _events(session, user, session_id: int, events: list[dict]) -> dict:
    response = await v2_post(session, user.telegram_id, f"{LIVE}/{session_id}/events", {"events": events})
    assert response.status_code == 200, response.text
    return response.json()


async def _checks(session, session_id: int, user) -> list[tuple]:
    detail = await TrainingSessionRepository(session).get_for_user(session_id, user.id)
    return [(b.technique_valid, b.rest_within_limit) for b in sorted(detail.blocks, key=lambda b: b.order_index)]


async def _a_day(session, user_id: int, **enrol):
    user = await _user(session, user_id)
    program = await _pullups(session)
    inclusion = await _enrol(session, user, program, course_inputs=WEIGHTED_INPUTS, **enrol)
    occurrences = await _main_occurrences(session, user)
    return user, inclusion, occurrences, await _start(session, user, occurrences[0]["id"])


async def _run(session, user, body: dict, values_by_block: list[list[int]], *, stop_before_last: bool = False) -> dict:
    """Ожидания — «Начать сейчас» (skip_wait), подходы — submit_result; stop_before_last — без последнего.
    Останавливается в CONFIRM (ждёт ответа) или на завершении."""
    queues = [list(values) for values in values_by_block]
    total = sum(len(q) for q in queues)
    sent, response = 0, body
    while response["engine"]["state"]["status"] == "active" and response["engine"]["state"]["phase"] != "CONFIRM":
        state = response["engine"]["state"]
        cursor = state["cursor"]
        if state["phase"] in ("PREP", "REST"):
            response = await _event(session, user, body["id"], "skip_wait", {"phase_seq": state["phase_seq"]})
            continue
        if stop_before_last and sent == total - 1:
            return response
        response = await _event(session, user, body["id"], "submit_result", {
            "block_index": cursor["block_index"], "set_index": cursor["set_index"], "round_index": cursor["round_index"],
            "value": queues[cursor["block_index"]].pop(0),
        })
        sent += 1
    return response


def _rests(plan: dict) -> tuple[list[list[int | None]], list[int | None]]:
    return (
        [[s["rest_after_seconds"] for s in block["sets"]] for block in plan["blocks"]],
        [block["rest_after_block_seconds"] for block in plan["blocks"]],
    )


async def _backdate(session, session_id: int, at) -> None:
    await session.execute(update(TrainingSession).where(TrainingSession.id == session_id).values(
        performed_at=at, started_at=at, completed_at=at + timedelta(minutes=50), ended_at=at + timedelta(minutes=50),
    ))
    await session.flush()


async def test_engine_plan_carries_v5_rules_rests_and_display(session, clock):  # noqa: F811
    user, _, occurrences, a_day = await _a_day(session, 305601)
    plan = a_day["engine"]["plan"]
    a_sets, a_blocks = _rests(plan)
    assert a_sets == [[240, 240, 240, None], [180, 180, 180, 180, None]]  # объём A 240, сила 180
    assert a_blocks == [900, None]  # объём → сила 900, не умолчание движка 90
    assert [b.get("confirm_checks") for b in plan["blocks"]] == [True, True]
    assert [b.get("stop_at_or_below") for b in plan["blocks"]] == [None, None]  # стоп-правило — только у B
    amrap = plan["blocks"][0]["sets"][-1]
    assert (amrap["kind"], amrap["marker"], amrap["min_target"]) == ("max_reps", "amrap", 17)  # p4 показан
    assert a_day["engine"]["state"]["checks"] == [None, None]
    a_done = await _run(session, user, a_day, [[17, 17, 17, 18], [5] * 5])
    assert a_done["engine"]["state"]["phase"] == "CONFIRM" and a_done["status"] == "started"
    await _event(session, user, a_day["id"], "confirm_blocks", {"checks": VALID})
    await _backdate(session, a_day["id"], MON)

    clock(MON + timedelta(days=3))
    b_day = await _start(session, user, occurrences[1]["id"])
    b_plan = b_day["engine"]["plan"]
    b_sets, b_blocks = _rests(b_plan)
    assert set(b_sets[0][:-1]) == {30} and b_sets[0][-1] is None  # объём B: 30 с между подходами
    assert b_sets[1] == [180, 180, 180, 180, None] and b_blocks == [900, None]
    assert [b.get("stop_at_or_below") for b in b_plan["blocks"]] == [2, None]
    assert {s["marker"] for s in b_plan["blocks"][0]["sets"]} == {"dynamic"}


async def test_confirmations_inside_engine_complete_once_and_unlock_green_a(session, clock):  # noqa: F811
    """Блокер 1: последний подход → CONFIRM (сессия не завершена, прогрессии нет); ответы valid → одно
    каноническое завершение; зелёный A (AMRAP ≥ p4 + 2, техника подтверждена) и прибавка веса достижимы."""
    user, inclusion, _, body = await _a_day(session, 305602)
    at_confirm = await _run(session, user, body, [[17, 17, 17, 19], [5] * 5])
    assert at_confirm["status"] == "started" and at_confirm["engine"]["state"]["phase"] == "CONFIRM"
    assert at_confirm["engine"]["state"]["phase_deadline_at"] is None
    await session.refresh(inclusion)
    assert inclusion.progression_state_rev == 0  # прогрессии до ответа нет

    partial = await _event(session, user, body["id"], "confirm_blocks", {"checks": VALID[:1]})
    assert partial["status"] == "started" and partial["engine"]["state"]["phase"] == "CONFIRM"
    done = await _event(session, user, body["id"], "confirm_blocks", {"checks": VALID[1:]})
    assert done["status"] == "completed" and done["engine_status"] == "completed"
    volume, strength = done["course_progression"]["blocks"]
    assert (volume["block_role"], volume["decision"]) == ("a_volume", "add_mandatory_rep")
    assert (strength["block_role"], strength["decision"]) == ("a_weighted_strength", "increase_load")
    assert await _checks(session, body["id"], user) == [(True, True), (True, True)]
    await session.refresh(inclusion)
    assert (inclusion.progression_state_rev, inclusion.sequence_cursor) == (1, 1)
    row = await session.get(TrainingSession, body["id"])
    await session.refresh(row)
    assert row.status.value == "completed" and row.superseded_at is None and row.engine_version == 2  # #308
    assert row.ended_at == from_ms(at_confirm["engine"]["state"]["phase_started_at"])  # длительность — до CONFIRM

    # Повторы: подтверждение после завершения — no-op; повторный complete — already_completed; копия — без
    # прогрессии и кредита; ничего не возвращается в started.
    late = await _event(session, user, body["id"], "confirm_blocks", {"checks": [
        {"block_index": 0, "technique": "invalid", "rest": "invalid"},
    ]})
    assert late["event_results"][0]["outcome"] == "noop" and late["status"] == "completed"
    again = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {
        "abandoned": False, "block_checks": [{"block_index": 0, "technique_valid": False, "rest_within_limit": False}],
    })
    assert again.status_code == 200 and again.json()["progression_skipped_reason"] == "already_completed"
    assert await _checks(session, body["id"], user) == [(True, True), (True, True)]
    clone = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{body['id']}/clone", {
        "performed_at": (MON + timedelta(days=1)).isoformat(),
    })
    assert clone.status_code == 201, clone.text
    await session.refresh(inclusion)
    assert (inclusion.progression_state_rev, inclusion.sequence_cursor) == (1, 1)
    journal = (await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")).json()["sessions"]
    assert sorted(c["id"] for c in journal) == sorted([body["id"], clone.json()["id"]])  # #308: по одному разу
    clone_row = await session.get(TrainingSession, clone.json()["id"])
    assert clone_row.plan_item_id is None  # копия не засчитывает занятие плана
    assert await LiveEngineService(session).rebuild_state(body["id"]) == row.engine_state  # воспроизводимость


async def test_unknown_answers_complete_but_block_increases(session, clock):  # noqa: F811
    user, _, _, body = await _a_day(session, 305603)
    await _run(session, user, body, [[17, 17, 17, 19], [5] * 5])
    done = await _event(session, user, body["id"], "confirm_blocks", {"checks": [
        {"block_index": 0, "technique": None, "rest": None}, {"block_index": 1, "technique": None, "rest": None},
    ]})
    assert done["status"] == "completed"
    volume, strength = done["course_progression"]["blocks"]
    assert (volume["decision"], volume["reason"]) == ("repeat", "unconfirmed")  # запас +2 есть, техника неизвестна
    assert strength["decision"] != "increase_load"
    assert await _checks(session, body["id"], user) == [(None, None), (None, None)]


async def test_invalid_technique_answer_is_recorded_not_unknown(session, clock):  # noqa: F811
    user, _, _, body = await _a_day(session, 305604)
    await _run(session, user, body, [[17, 17, 17, 19], [5] * 5])
    await _event(session, user, body["id"], "confirm_blocks", {"checks": [
        {"block_index": 0, "technique": "invalid", "rest": "valid"}, {"block_index": 1, "technique": "valid", "rest": "invalid"},
    ]})
    assert await _checks(session, body["id"], user) == [(False, True), (True, False)]


async def test_pause_in_set_rest_is_a_server_fact_rest_not_within_limit(session, clock):  # noqa: F811
    """Пользователь отвечает «отдых в пределах», но в отдыхе между подходами блока была пауза — сервер
    записывает «отдых превышен»; сам «в пределах» без ответа не ставится."""
    user, _, _, body = await _a_day(session, 305605)
    state = body["engine"]["state"]
    if state["phase"] == "PREP":
        state = (await _event(session, user, body["id"], "skip_wait", {"phase_seq": state["phase_seq"]}))["engine"]["state"]
    rest = (await _event(session, user, body["id"], "submit_result", {
        "block_index": 0, "set_index": 0, "round_index": None, "value": 17,
    }))["engine"]["state"]
    assert rest["phase"] == "REST" and rest["rest_kind"] == "set"
    paused = (await _event(session, user, body["id"], "pause", {"phase_seq": rest["phase_seq"]}))["engine"]["state"]
    assert paused["rest_paused"] == [0]
    resumed = await _event(session, user, body["id"], "resume", {"phase_seq": paused["phase_seq"]})
    await _run(session, user, resumed | {"id": body["id"]}, [[17, 17, 19], [5] * 5])
    await _event(session, user, body["id"], "confirm_blocks", {"checks": VALID})
    assert await _checks(session, body["id"], user) == [(True, False), (True, True)]


async def _b_day(session, user_id: int):
    """Первая A подтверждена (опорный объём для B), затем старт B через 3 дня."""
    user, inclusion, occurrences, a_day = await _a_day(session, user_id)
    await _run(session, user, a_day, [[17, 17, 17, 18], [5] * 5])
    await _event(session, user, a_day["id"], "confirm_blocks", {"checks": VALID})
    await _backdate(session, a_day["id"], MON)
    clock_at = MON + timedelta(days=3)
    return user, inclusion, occurrences, clock_at


async def test_b_stop_at_two_ends_only_volume_then_strength_and_counts_the_set(session, clock):  # noqa: F811
    user, _, occurrences, at = await _b_day(session, 305606)
    clock(at)
    b_day = await _start(session, user, occurrences[1]["id"])
    q = b_day["engine"]["plan"]["blocks"][0]["sets"][0]["target"]
    sets_b = len(b_day["engine"]["plan"]["blocks"][0]["sets"])
    after = await _run(session, user, b_day, [[q, q, 2], [5] * 5])
    state = after["engine"]["state"]
    assert state["stopped_blocks"] == [{"block_index": 0, "reason": "low_reps"}]
    assert state["phase"] == "CONFIRM"  # сила выполнена (не пропущена), тренировка не отменена
    assert [log["block_index"] for log in state["logs"]] == [0, 0, 0, 1, 1, 1, 1, 1]
    done = await _event(session, user, b_day["id"], "confirm_blocks", {"checks": VALID})
    assert done["status"] == "completed"
    volume, strength = done["course_progression"]["blocks"]
    assert volume["block_role"] == "b_volume" and volume["details"]["stop_reason"] == "low_reps"
    assert volume["fact_volume"] == 2 * q + 2  # подход «2» входит в VB_fact
    assert volume["decision"] == "hold"  # S×q не закрыт — ступень не открывается
    assert strength["block_role"] == "b_weighted_strength"
    row = await session.get(TrainingSession, b_day["id"])
    await session.refresh(row)
    assert row.status.value == "completed" and sets_b > 3


async def test_b_three_reps_continue_and_invalid_technique_stops(session, clock):  # noqa: F811
    user, _, occurrences, at = await _b_day(session, 305607)
    clock(at)
    b_day = await _start(session, user, occurrences[1]["id"])
    state = b_day["engine"]["state"]
    if state["phase"] == "PREP":
        state = (await _event(session, user, b_day["id"], "skip_wait", {"phase_seq": state["phase_seq"]}))["engine"]["state"]
    three = (await _event(session, user, b_day["id"], "submit_result", {
        "block_index": 0, "set_index": 0, "round_index": None, "value": 3,
    }))["engine"]["state"]
    assert three["phase"] == "REST" and three["rest_kind"] == "set"  # 3 — продолжать
    work = (await _event(session, user, b_day["id"], "skip_wait", {"phase_seq": three["phase_seq"]}))["engine"]["state"]
    broken = (await _event(session, user, b_day["id"], "submit_result", {
        "block_index": 0, "set_index": 1, "round_index": None, "value": 5, "technique": "invalid",
    }))["engine"]["state"]
    assert work["phase"] == "WORK"
    assert broken["stopped_blocks"] == [{"block_index": 0, "reason": "technique"}]
    assert (broken["phase"], broken["rest_kind"]) == ("REST", "block")
    done = await _run(session, user, {"id": b_day["id"], "engine": {"state": broken}}, [[], [5] * 5])
    final = await _event(session, user, b_day["id"], "confirm_blocks", {"checks": VALID})
    assert done["engine"]["state"]["phase"] == "CONFIRM" and final["status"] == "completed"
    volume = final["course_progression"]["blocks"][0]
    assert volume["details"]["stop_reason"] == "technique" and volume["fact_volume"] == 8
    assert (await _checks(session, b_day["id"], user))[0] == (False, True)  # остановка по технике — False


async def test_last_set_with_exit_in_one_batch_completes_once_either_order(session, clock):  # noqa: F811
    """Гонка «последний подход + выход»: оба порядка в одном пакете (как офлайн-очередь) — одно завершение."""
    for user_id, exit_first in ((305608, False), (305609, True)):
        user, inclusion, _, body = await _a_day(session, user_id)
        before_last = await _run(session, user, body, [[17, 17, 17, 19], [5] * 5], stop_before_last=True)
        cursor = before_last["engine"]["state"]["cursor"]
        last = {"client_event_id": str(uuid.uuid4()), "type": "submit_result", "payload": {
            "block_index": cursor["block_index"], "set_index": cursor["set_index"], "round_index": None, "value": 5,
        }}
        leave = {"client_event_id": str(uuid.uuid4()), "type": "finish_early", "payload": {"checks": VALID}}
        batch = [leave, last] if exit_first else [last, leave]
        response = await _events(session, user, body["id"], batch)
        assert response["status"] == "completed"
        assert [r["outcome"] for r in response["event_results"]] == (["applied", "noop"] if exit_first else ["applied", "applied"])
        replay = await _events(session, user, body["id"], batch)  # потерянный ответ — пакет досылается снова
        assert [r["outcome"] for r in replay["event_results"]] == ["duplicate", "duplicate"]
        await session.refresh(inclusion)
        # Выход раньше последнего подхода — недоделка (abandoned, #307: без прогрессии); иначе — ровно одна.
        assert inclusion.progression_state_rev == (0 if exit_first else 1)
        assert await _checks(session, body["id"], user) == [(True, True), (True, True)]
        row = await session.get(TrainingSession, body["id"])
        await session.refresh(row)
        assert await LiveEngineService(session).rebuild_state(body["id"]) == row.engine_state


async def test_http_complete_during_confirm_carries_checks_through_the_event_log(session, clock):  # noqa: F811
    """POST …/complete (старый клиент, второе устройство) в CONFIRM: подтверждения запроса — payload серверного
    finish_early в журнале событий; завершение одно, rebuild совпадает."""
    user, inclusion, _, body = await _a_day(session, 305610)
    await _run(session, user, body, [[17, 17, 17, 19], [5] * 5])
    response = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {
        "abandoned": False, "block_checks": CONFIRMED,
    })
    assert response.status_code == 200, response.text
    assert response.json()["course_progression"]["blocks"][0]["decision"] == "add_mandatory_rep"
    assert await _checks(session, body["id"], user) == [(True, True), (True, True)]
    events = await SessionEventRepository(session).list_for_session(body["id"])
    finish = [e for e in events if e.type == "finish_early"]
    assert len(finish) == 1 and finish[0].payload["checks"][0] == {"block_index": 0, "technique": "valid", "rest": "valid"}
    row = await session.get(TrainingSession, body["id"])
    await session.refresh(row)
    assert await LiveEngineService(session).rebuild_state(body["id"]) == row.engine_state
    await session.refresh(inclusion)
    assert inclusion.progression_state_rev == 1


async def test_explicit_early_finish_with_checks_mid_workout(session, clock):  # noqa: F811
    """Выход до конца: подтверждения запроса записываются, недоделка — abandoned (прогрессия по факту)."""
    user, _, _, body = await _a_day(session, 305611)
    await _run(session, user, body, [[17, 17, 17, 18], [5] * 5], stop_before_last=True)
    response = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {
        "abandoned": False, "block_checks": CONFIRMED,
    })
    assert response.status_code == 200, response.text
    detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
    assert detail.status.value == "completed"
    assert [(b.technique_valid, b.rest_within_limit) for b in detail.blocks] == [(True, True), (True, True)]


async def test_amrap_below_p4_is_recorded_as_red_not_rejected(session, clock):  # noqa: F811
    user, _, _, body = await _a_day(session, 305612)
    await _run(session, user, body, [[17, 17, 17, 9], [5] * 5])
    done = await _event(session, user, body["id"], "confirm_blocks", {"checks": VALID})
    volume = done["course_progression"]["blocks"][0]
    assert (volume["decision"], volume["reason"]) == ("repeat", "red")
    detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
    a_block = min(detail.blocks, key=lambda b: b.order_index)
    assert max(log.set_number for log in a_block.set_logs) == 4
    assert [int(log.value) for log in sorted(a_block.set_logs, key=lambda log: log.set_number)] == [17, 17, 17, 9]


async def test_assisted_control_set_above_cap_is_stored_as_entered_and_counted_as_eight(session, clock):  # noqa: F811
    """V5.6 §7: контрольный пятый 5–8, жёсткий потолок 8 — факт выше 8 записывается как введён (история не
    обрезается молча), в расчёт идёт 8; пятый < 5 — недобор (increase), не ошибка API."""
    band = {"kind": "band", "name": "Синяя", "colour": "синяя", "attachment": "петля", "body_position": "стопа"}
    inputs = {"volume_capacity": 10, "volume_assistance": band, "strength_assistance": band}
    for user_id, control, intent in ((305613, 10, "decrease_assistance"), (305614, 4, "increase_assistance")):
        user = await _user(session, user_id)
        await _enrol(session, user, await _pullups(session), fresh_max=4, course_inputs=inputs)
        body = await _start(session, user, (await _main_occurrences(session, user))[0]["id"])
        control_spec = body["engine"]["plan"]["blocks"][1]["sets"][-1]
        assert (control_spec["kind"], control_spec["target"], control_spec["marker"], control_spec["cap"]) == ("reps", 5, "control", 8)
        await _run(session, user, body, [[7, 7, 7, 9], [5, 5, 5, 5, control]])
        done = await _event(session, user, body["id"], "confirm_blocks", {"checks": VALID})
        strength = done["course_progression"]["blocks"][1]
        assert (strength["block_role"], strength["assistance_intent"]) == ("assisted_strength", intent)
        detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
        strength_block = max(detail.blocks, key=lambda b: b.order_index)
        assert int(max(strength_block.set_logs, key=lambda log: log.set_number).value) == control


async def test_v5_completion_repeat_replay_and_clone_preserve_existing_rewards_without_duplicates(session, clock):  # noqa: F811
    """Геймификация (#305 × интеграция): у завершения TrainingSession v2 политики наград нет (PROJECT_SPEC
    «Монеты v2 не работают» — решение владельца, шов). Здесь закреплено только то, что нельзя сломать:
    существующие монеты и ачивки сохраняются; завершение V5.6, повтор, дубль событий и копия ничего не
    начисляют повторно и ничего не списывают."""
    from sqlalchemy import func, select

    from app.db.models import Achievement, Coin, CoinReason
    from app.services.gamification import GamificationService

    user, _, _, body = await _a_day(session, 305615)
    gamification = GamificationService(session)
    await gamification.award_workout_coins(user.id, 7)
    await gamification.unlock_achievement(user_id=user.id, code=AchievementCode.FIRST_BASELINE, coins_reward=3)
    await session.flush()

    async def snapshot():
        await session.refresh(user)
        coins = await session.scalar(select(func.count(Coin.id)).where(Coin.user_id == user.id))
        codes = sorted((await session.execute(select(Achievement.code).where(Achievement.user_id == user.id))).scalars())
        return user.coins_balance, coins, codes

    before = await snapshot()
    assert before == (10, 2, ["first_baseline"])
    await _run(session, user, body, [[17, 17, 17, 19], [5] * 5])
    confirm = {"client_event_id": str(uuid.uuid4()), "type": "confirm_blocks", "payload": {"checks": VALID}}
    assert (await _events(session, user, body["id"], [confirm]))["status"] == "completed"
    await _events(session, user, body["id"], [confirm])  # дубль (потерянный ответ)
    await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {"abandoned": False})
    clone = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{body['id']}/clone", {
        "performed_at": (MON + timedelta(days=1)).isoformat(),
    })
    assert clone.status_code == 201, clone.text
    assert await snapshot() == before
    workout_awards = await session.scalar(
        select(func.count(Coin.id)).where(Coin.user_id == user.id, Coin.reason == CoinReason.WORKOUT_COMPLETED),
    )
    assert workout_awards == 1  # только начисление, сделанное до теста
