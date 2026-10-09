"""PATCH /api/v2/sessions/{id} и POST /api/v2/sessions/{id}/clone (#262)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    ProgramInclusion,
    SessionBlock,
    SessionPlanItem,
    SetLog,
    TrainingSession,
)
from app.services.training_analytics import resolve_timezone
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch, v2_post
from tests.test_web.test_v2_journal_v2 import _complete, _finished_mixed_session
from tests.test_web.test_v2_live_session import _setup_step_session
from tests.test_web.test_v2_mixed_workout import REPS, _exercise, _start, _user, _workout_plan_item
from tests.test_web.test_v2_sessions_journal import _start_and_complete


def _local(user: User, moment: datetime | str):
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    return moment.astimezone(resolve_timezone(user.timezone))


def _local_today(user: User):
    return _local(user, datetime.now(UTC)).date()


async def _listed(session: AsyncSession, user: User) -> list[dict]:
    response = await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")
    return response.json()["sessions"]


async def _simple_session(session: AsyncSession, user: User) -> int:
    pull = await _exercise(session, "Подтягивания")
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS)])
    body = await _start(session, user, plan_item_id)
    # live-подходы пишутся батчем в _run_standard_block; здесь достаточно завершить
    await _complete(session, user, body["id"])
    return body["id"]


async def _finished_with_logs(session: AsyncSession, user: User) -> int:
    session_id, _ = await _finished_mixed_session(session, user)
    return session_id


async def test_edit_changes_sets_effort_comment_and_date(session: AsyncSession):
    user = await _user(session, 962001)
    session_id = await _finished_with_logs(session, user)
    [card] = await _listed(session, user)
    assert card["can_edit"] is True
    before_logs = card["blocks"][0]["set_logs"]
    assert len(before_logs) == 2

    target_day = _local_today(user) - timedelta(days=3)
    response = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{session_id}", {
        "performed_on": target_day.isoformat(), "effort": "4", "comment": "  тяжело  ",
        "sets": [{"block_index": 0, "set_number": 1, "value": "11", "effort": "3.5", "note": "рывком"}],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["effort"] == "4.0" and body["comment"] == "тяжело"
    first, second = body["blocks"][0]["set_logs"]
    assert (first["value"], first["effort"], first["note"]) == ("11.00", "3.5", "рывком")
    assert second["value"] == before_logs[1]["value"]
    assert _local(user, body["performed_at"]).date() == target_day
    assert body["can_edit"] is True

    # календарь отражает перенос
    month = target_day.strftime("%Y-%m")
    days = (await v2_get(session, user.telegram_id, f"/api/v2/journal/days?month={month}")).json()["days"]
    assert {"date": target_day.isoformat(), "count": 1} in days

    cleared = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{session_id}", {"comment": None, "effort": None})
    assert cleared.json()["comment"] is None and cleared.json()["effort"] is None


async def test_edit_validation(session: AsyncSession):
    user = await _user(session, 962002)
    session_id = await _finished_with_logs(session, user)
    path = f"/api/v2/sessions/{session_id}"
    tomorrow = (_local_today(user) + timedelta(days=2)).isoformat()

    assert (await v2_patch(session, user.telegram_id, path, {"performed_on": tomorrow})).status_code == 422
    assert (await v2_patch(session, user.telegram_id, path, {"effort": "9"})).status_code == 422
    bad_set = {"sets": [{"block_index": 0, "set_number": 1, "value": "-1"}]}
    assert (await v2_patch(session, user.telegram_id, path, bad_set)).status_code == 422
    unknown = {"sets": [{"block_index": 0, "set_number": 99, "value": "5"}]}
    assert (await v2_patch(session, user.telegram_id, path, unknown)).status_code == 422
    duplicate = {"sets": [{"block_index": 0, "set_number": 1, "value": "5"}] * 2}
    assert (await v2_patch(session, user.telegram_id, path, duplicate)).status_code == 422
    # ничего не применилось (в т.ч. первый корректный подход при ошибке во втором)
    mixed = {"sets": [
        {"block_index": 0, "set_number": 1, "value": "77"}, {"block_index": 0, "set_number": 99, "value": "5"},
    ]}
    assert (await v2_patch(session, user.telegram_id, path, mixed)).status_code == 422
    [card] = await _listed(session, user)
    assert card["blocks"][0]["set_logs"][0]["value"] != "77.00"


async def test_edit_and_clone_ownership_and_missing_are_404(session: AsyncSession):
    owner = await _user(session, 962003)
    stranger = await _user(session, 962004)
    session_id = await _finished_with_logs(session, owner)

    for who, target in ((stranger, session_id), (owner, 999999)):
        assert (await v2_patch(session, who.telegram_id, f"/api/v2/sessions/{target}", {"effort": "3"})).status_code == 404
        assert (await v2_post(session, who.telegram_id, f"/api/v2/sessions/{target}/clone", {})).status_code == 404
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 1
    assert (await _listed(session, owner))[0]["effort"] is None


async def test_active_is_409_course_session_editable_cloneable_not_deletable(session: AsyncSession, user: User):
    # STEP/program-backed
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    step_id = await _start_and_complete(
        session, user, [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        exercise_id=roles["block_a"], value="10",
    )
    # активная
    pull = await _exercise(session, "Активное")
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS)], title="Активная")
    running = await _start(session, user, plan_item_id)

    # Активная: ни правки, ни копии.
    patch = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{running['id']}", {"comment": "x"})
    clone = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{running['id']}/clone", {})
    assert patch.status_code == 409 and clone.status_code == 409 and patch.json()["detail"]

    # #307 B1 (решение владельца): сессия курса правится целиком и копируется — прогрессию двигает только
    # подход на максимум и только вперёд; удаление — прежний строгий предикат: нет.
    step_path = f"/api/v2/sessions/{step_id}"
    assert (await v2_patch(session, user.telegram_id, step_path, {"comment": "x"})).status_code == 200
    changed = await v2_patch(session, user.telegram_id, step_path, {
        "sets": [{"block_index": 0, "set_number": 1, "value": "11"}],
    })
    assert changed.status_code == 200, changed.text
    [card] = await _listed(session, user)  # активная в списке завершённых не показывается
    assert card["can_edit"] is True and card["can_clone"] is True and card["can_delete"] is False
    assert card["blocks"][0]["set_logs"][0]["value"] == "11.00" and card["comment"] == "x"
    assert (await v2_delete(session, user.telegram_id, step_path)).status_code == 409
    cloned = await v2_post(session, user.telegram_id, f"{step_path}/clone", {})
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["plan_item_id"] is None
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 3


async def test_session_without_proven_workout_is_editable_but_not_deletable(session: AsyncSession):
    """#307 (ED1, D9): правка больше не требует доказательства для удаления — сессия без снимка и
    связи с тренировкой, не учтённая прогрессией, правится; удаление по-прежнему запрещено."""
    user = await _user(session, 962005)
    session_id = await _finished_with_logs(session, user)
    await session.execute(update(TrainingSession).where(TrainingSession.id == session_id).values(
        workout_snapshot=None, plan_item_id=None,  # #304: явный кредит — тоже связь с Workout
        workout_definition_id=None, prescription_snapshot=None,  # #307: явная идентичность — тоже
    ))
    await session.execute(SessionPlanItem.__table__.delete().where(SessionPlanItem.session_id == session_id))
    await session.commit()
    response = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{session_id}", {"comment": "x"})
    assert response.status_code == 200 and response.json()["can_delete"] is False
    assert (await v2_delete(session, user.telegram_id, f"/api/v2/sessions/{session_id}")).status_code == 409


async def test_clone_copies_tree_as_backdated_without_progression(session: AsyncSession):
    user = await _user(session, 962006)
    original_id = await _finished_with_logs(session, user)
    await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{original_id}", {"effort": "4", "comment": "ок"})
    plan_items_before = await session.scalar(select(func.count()).select_from(PlanItem))
    complexes_before = await session.scalar(select(func.count()).select_from(Complex))
    items_before = await session.scalar(select(func.count()).select_from(ComplexItem))
    exercises_before = await session.scalar(select(func.count()).select_from(Exercise))
    [original] = await _listed(session, user)

    response = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{original_id}/clone", {})
    assert response.status_code == 201
    clone = response.json()
    assert clone["id"] != original_id and clone["source"] == "backdated" and clone["status"] == "completed"
    assert _local(user, clone["performed_at"]).date() == _local_today(user)
    assert clone["effort"] == "4.0" and clone["comment"] == "ок" and clone["title"] == original["title"]
    assert clone["can_edit"] is True and clone["can_delete"] is True
    assert clone["progression_result"] is None

    def shape(card: dict) -> list:
        return [
            (b["order_index"], b["exercise_id"], b["protocol_type"], b["exercise_name"], b["result"],
             [(t["set_number"], t["value"], t["unit"]) for t in b["set_targets"]],
             [(s["set_number"], s["value"], s["unit"], s["effort"], s["note"]) for s in b["set_logs"]])
            for b in card["blocks"]
        ]

    assert shape(clone) == shape(original)
    # оригинал не тронут, определения/план — тоже
    assert shape((await _listed(session, user))[1]) == shape(original)
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 2
    assert await session.scalar(select(func.count()).select_from(PlanItem)) == plan_items_before
    assert await session.scalar(select(func.count()).select_from(Complex)) == complexes_before
    assert await session.scalar(select(func.count()).select_from(ComplexItem)) == items_before
    assert await session.scalar(select(func.count()).select_from(Exercise)) == exercises_before
    assert await session.scalar(select(func.count()).select_from(SessionBlock)) == 6
    # правка копии не трогает оригинал
    await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{clone['id']}", {
        "sets": [{"block_index": 0, "set_number": 1, "value": "30"}],
    })
    assert (await session.scalar(
        select(func.count()).select_from(SetLog).where(SetLog.value == 30),
    )) == 1


async def test_clone_date_default_explicit_and_future(session: AsyncSession):
    user = await _user(session, 962007)
    session_id = await _finished_with_logs(session, user)
    path = f"/api/v2/sessions/{session_id}/clone"

    past = _local_today(user) - timedelta(days=10)
    response = await v2_post(session, user.telegram_id, path, {"performed_on": past.isoformat()})
    assert response.status_code == 201
    assert _local(user, response.json()["performed_at"]).date() == past
    assert (await v2_post(
        session, user.telegram_id, path, {"performed_on": (_local_today(user) + timedelta(days=2)).isoformat()},
    )).status_code == 422

    default = await v2_post(session, user.telegram_id, path, {})
    performed = datetime.fromisoformat(default.json()["performed_at"])
    assert _local(user, performed).date() == _local_today(user) and performed <= datetime.now(UTC)


async def test_edit_and_clone_do_not_mutate_progression(session: AsyncSession, user: User):
    """Цели STEP-плана не меняются ни правкой, ни клоном Builder-сессии."""
    await _setup_step_session(session, user)

    async def plan_state():
        plan = (await session.execute(
            select(PlanItem.id, PlanItem.program_inclusion_id, PlanItem.count_per_week).order_by(PlanItem.id),
        )).all()
        inclusions = (await session.execute(
            select(ProgramInclusion.id, ProgramInclusion.snapshot).order_by(ProgramInclusion.id),
        )).all()
        return plan, inclusions

    before = await plan_state()
    session_id = await _simple_session(session, user)
    await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{session_id}", {"comment": "ок"})
    clone = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{session_id}/clone", {})
    assert clone.status_code == 201
    after = await plan_state()
    assert before[1] and after[1] == before[1]  # снимки инклюзий (цели STEP) те же
    assert [row for row in after[0] if row[0] in {r[0] for r in before[0]}] == before[0]
