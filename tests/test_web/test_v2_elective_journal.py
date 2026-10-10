"""#279 (P0 владельца) — «Факультатив — 3 минуты подтягиваний» в Журнале v2.

Это TrainingSession(source=elective), перенесённая backfill-ом (#163) из legacy ElectiveWorkout:
системное Exercise «Факультатив — …» (subcategory elective_*), без снимка и без связи с PlanItem.
Раньше предикат безопасного удаления (PROJECT_SPEC §3) такие записи не доказывал (REASON_UNPROVEN),
и в Журнале не было ни «Изменить», ни «Удалить». Теперь доказанный факультатив правится/удаляется;
всё недоказанное по-прежнему отказ."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ElectiveWorkout, User
from app.db.models_program import Exercise, SessionBlock, SessionStatus, SetLog, TrainingSession
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.multi_program import MetricType, SessionSource
from app.services.training_analytics import resolve_timezone
from scripts.backfill_multi_program import (
    _ELECTIVE_EXERCISE_NAMES,
    _create_training_session_for_elective,
    _get_or_create_exercise,
)
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch, v2_post
from tests.test_web.test_v2_journal_log import _backdated
from tests.test_web.test_v2_mixed_workout import _user

THREE_MINUTES = ElectiveType.THREE_MINUTES
TITLE = "Факультатив — 3 минуты подтягиваний"


async def _backfilled_elective(
    session: AsyncSession, user: User, elective_type: ElectiveType = THREE_MINUTES, sequence=(4, 3, 2),
    ago: timedelta = timedelta(minutes=30),
) -> tuple[ElectiveWorkout, int]:
    """Ровно так, как это делает backfill: legacy-строка + TrainingSession(source=elective)."""
    elective = ElectiveWorkout(
        user_id=user.id, elective_type=elective_type, performed_at=datetime.now(UTC) - ago,
        reps_sequence=list(sequence), total_reps=sum(sequence), equipment_type=EquipmentType.BAND,
        equipment_value=Decimal("15.0"),
    )
    session.add(elective)
    await session.flush()
    exercise = await _get_or_create_exercise(
        session, name=_ELECTIVE_EXERCISE_NAMES[elective_type], subcategory=f"elective_{elective_type.value}",
    )
    await _create_training_session_for_elective(session, elective, exercise_id=exercise.id)
    training = await session.scalar(
        select(TrainingSession).where(TrainingSession.user_id == user.id).order_by(TrainingSession.id.desc()),
    )
    return elective, training.id


async def _listed(session: AsyncSession, user: User) -> list[dict]:
    return (await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")).json()["sessions"]


async def test_backfilled_elective_is_the_object_and_is_deletable_editable(session: AsyncSession):
    user = await _user(session, 962791)
    await _backfilled_elective(session, user)

    [card] = await _listed(session, user)
    assert card["source"] == "elective" and card["title"] is None
    assert card["blocks"][0]["exercise_name"] == TITLE
    assert card["can_delete"] is True and card["can_edit"] is True
    # сырой упакованный JSON наружу не отдаётся — читаемая строка
    assert card["blocks"][0]["set_logs"][0]["note"] == "Подходы: 4 · 3 · 2"
    assert "{" not in json.dumps(card["blocks"][0]["set_logs"][0]["note"])
    assert card["blocks"][0]["set_logs"][0]["value"] == "9.00"


async def test_delete_elective_supersedes_the_copy_and_keeps_legacy_rows(session: AsyncSession):
    user = await _user(session, 962792)
    elective, session_id = await _backfilled_elective(session, user)
    other_elective, other_id = await _backfilled_elective(
        session, user, ElectiveType.W_LADDER, sequence=(5, 4, 3), ago=timedelta(minutes=90),
    )
    exercise_ids = set(await session.scalars(select(Exercise.id).where(Exercise.name.like("Факультатив — %"))))

    response = await v2_delete(session, user.telegram_id, f"/api/v2/sessions/{session_id}")
    assert response.status_code == 204

    assert [card["id"] for card in await _listed(session, user)] == [other_id]
    # #308: legacy-строка факультатива остаётся, поэтому копия не удаляется, а ЗАМЕЩАЕТСЯ (иначе повторное
    # сведение воссоздало бы удалённую запись) — она вне canonical_sessions и никуда не попадает
    deleted = await session.get(TrainingSession, session_id)
    await session.refresh(deleted)
    assert deleted.superseded_at is not None and deleted.superseded_reason == "legacy_deleted"
    assert deleted.legacy_id == elective.id
    # соседняя запись, legacy-строки и определения Exercise не тронуты
    other = await session.get(TrainingSession, other_id)
    assert other is not None and other.superseded_at is None
    assert await session.scalar(select(func.count()).select_from(ElectiveWorkout)) == 2
    assert await session.get(ElectiveWorkout, elective.id) is not None
    assert set(await session.scalars(select(Exercise.id).where(Exercise.name.like("Факультатив — %")))) == exercise_ids
    assert await session.scalar(select(func.count()).select_from(SessionBlock)) == 2
    assert other_elective.id is not None


async def test_edit_elective_changes_value_effort_comment_date_and_keeps_packed_note(session: AsyncSession):
    user = await _user(session, 962793)
    _, session_id = await _backfilled_elective(session, user)
    log = await session.scalar(select(SetLog).join(SessionBlock).where(SessionBlock.session_id == session_id))
    packed_before = log.note
    assert json.loads(packed_before)["reps_sequence"] == [4, 3, 2]

    target_day = (datetime.now(UTC).astimezone(resolve_timezone(user.timezone)) - timedelta(days=2)).date()
    response = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{session_id}", {
        "performed_on": target_day.isoformat(), "effort": "4", "comment": "поправил",
        "sets": [{"block_index": 0, "set_number": 1, "value": "10", "effort": "3", "note": "СЫРОЙ JSON НЕ ТРОГАТЬ"}],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["effort"] == "4.0" and body["comment"] == "поправил"
    assert body["blocks"][0]["set_logs"][0]["value"] == "10.00"
    assert body["blocks"][0]["set_logs"][0]["effort"] == "3.0"
    # значение поправили (10 ≠ 4+3+2): разбивка скрыта, чтобы не противоречить «Факт: 10» (#283);
    # заметка из запроса проигнорирована
    assert body["blocks"][0]["set_logs"][0]["note"] is None
    assert body["can_delete"] is True
    await session.refresh(log)
    assert log.note == packed_before  # упакованный backfill-ом JSON не затёрт правкой


async def test_edit_back_to_the_sum_shows_the_breakdown_again(session: AsyncSession):
    user = await _user(session, 962799)
    _, session_id = await _backfilled_elective(session, user)
    patch = {"sets": [{"block_index": 0, "set_number": 1, "value": "10"}]}
    assert (await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{session_id}", patch)).status_code == 200
    [card] = await _listed(session, user)
    assert card["blocks"][0]["set_logs"][0]["note"] is None
    patch["sets"][0]["value"] = "9"
    assert (await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{session_id}", patch)).status_code == 200
    [card] = await _listed(session, user)
    assert card["blocks"][0]["set_logs"][0]["note"] == "Подходы: 4 · 3 · 2"


async def test_clone_of_elective_is_denied(session: AsyncSession):
    user = await _user(session, 962794)
    _, session_id = await _backfilled_elective(session, user)
    before = await session.scalar(select(func.count()).select_from(TrainingSession))

    response = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{session_id}/clone", {})
    assert response.status_code == 409
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == before


async def test_elective_ownership_is_404_and_untouched(session: AsyncSession):
    owner = await _user(session, 962795)
    stranger = await _user(session, 962796)
    _, session_id = await _backfilled_elective(session, owner)
    path = f"/api/v2/sessions/{session_id}"

    assert (await v2_delete(session, stranger.telegram_id, path)).status_code == 404
    assert (await v2_patch(session, stranger.telegram_id, path, {"effort": "2"})).status_code == 404
    assert await _listed(session, stranger) == []
    assert await session.get(TrainingSession, session_id) is not None


async def test_unproven_elective_shapes_stay_denied(session: AsyncSession):
    user = await _user(session, 962797)
    _, elective_session_id = await _backfilled_elective(session, user)
    elective_exercise = await session.scalar(select(Exercise).where(Exercise.name == TITLE))

    # 1) source=elective, но блок на обычное (не elective_*) системное Exercise.
    plain = Exercise(name="Обычное", metric_type=MetricType.REPS, category="t")
    # 2) source=elective, но блок на ПОЛЬЗОВАТЕЛЬСКОЕ упражнение с elective_*-подкатегорией.
    spoofed = Exercise(
        name="Подделка", metric_type=MetricType.REPS, category="t", subcategory="elective_three_minutes",
        source_type="user", owner_user_id=user.id,
    )
    session.add_all([plain, spoofed])
    await session.flush()
    denied_ids = []
    for exercise in (plain, spoofed):
        training = TrainingSession(
            user_id=user.id, source=SessionSource.ELECTIVE, status=SessionStatus.COMPLETED,
            performed_at=datetime.now(UTC) - timedelta(hours=3),
        )
        session.add(training)
        await session.flush()
        session.add(SessionBlock(session_id=training.id, order_index=0, exercise_id=exercise.id))
        await session.flush()
        denied_ids.append(training.id)
    # 3) НЕ elective-источник на elective-упражнении (backdated-запись) — недоказано.
    backdated = (await v2_post(
        session, user.telegram_id, "/api/v2/sessions", _backdated(elective_exercise.id),
    )).json()
    denied_ids.append(backdated["id"])

    cards = {card["id"]: card for card in await _listed(session, user)}
    assert cards[elective_session_id]["can_delete"] is True
    for session_id in denied_ids:
        # #307 (ED1): правка не зависит от доказательства для удаления (прогрессию эти записи не питают),
        # удаление недоказанного — по-прежнему отказ.
        assert cards[session_id]["can_delete"] is False and cards[session_id]["can_edit"] is True
        assert (await v2_delete(session, user.telegram_id, f"/api/v2/sessions/{session_id}")).status_code == 409
        assert await session.get(TrainingSession, session_id) is not None
