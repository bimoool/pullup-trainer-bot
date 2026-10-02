"""CRIMPD #263 — запись тренировки задним числом (source=backdated) и свободной
активности (source=freeform + activity_type/duration_seconds) через
POST /api/v2/sessions: валидация, владение, отображение в Журнале и Analytics."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import Exercise
from app.domain.multi_program import MetricType
from tests.test_web._v2_client import v2_delete, v2_get, v2_post
from tests.test_web.test_v2_mixed_workout import _user


def _past(days: int = 2) -> datetime:
    return (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0)


def _activity(**overrides) -> dict:
    payload = {
        "source": "freeform", "performed_at": _past().isoformat(), "blocks": [],
        "activity_type": "running", "duration_seconds": 45 * 60, "effort": "3", "comment": "парк",
    }
    payload.update(overrides)
    return payload


async def _exercise(session: AsyncSession, *, owner: User | None = None) -> Exercise:
    exercise = Exercise(
        name="Подтягивания", metric_type=MetricType.REPS, category="journal-log",
        source_type="user" if owner else "system", owner_user_id=owner.id if owner else None,
    )
    session.add(exercise)
    await session.flush()
    return exercise


def _backdated(exercise_id: int, **overrides) -> dict:
    payload = {
        "source": "backdated", "performed_at": _past().isoformat(), "effort": "4", "comment": "без таймера",
        "blocks": [{
            "exercise_id": exercise_id,
            "sets": [{"set_number": 1, "metric_type": "reps", "value": "8", "unit": "reps"}],
        }],
    }
    payload.update(overrides)
    return payload


async def test_freeform_activity_is_stored_and_listed(session: AsyncSession, user: User):
    response = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=_activity())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "freeform" and body["status"] == "completed"
    assert body["activity_type"] == "running" and body["duration_seconds"] == 2700
    assert body["title"] == "Бег" and body["blocks"] == [] and body["effort"] == "3.0"

    listed = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    [item] = listed.json()["sessions"]
    assert item["activity_type"] == "running" and item["duration_seconds"] == 2700 and item["title"] == "Бег"
    assert item["can_delete"] is True


async def test_freeform_activity_validation(session: AsyncSession, user: User):
    async def post(**overrides):
        return await v2_post(
            session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=_activity(**overrides),
        )

    assert (await post(duration_seconds=59)).status_code == 422
    assert (await post(duration_seconds=12 * 3600 + 1)).status_code == 422
    assert (await post(duration_seconds=None)).status_code == 422
    assert (await post(activity_type="parkour")).status_code == 422
    assert (await post(effort="6")).status_code == 422
    assert (await post(performed_at=(datetime.now(UTC) + timedelta(days=1)).isoformat())).status_code == 422
    assert (await post(duration_seconds=60)).status_code == 200
    assert (await post(duration_seconds=12 * 3600)).status_code == 200


async def test_activity_fields_rejected_for_other_sources(session: AsyncSession, user: User):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload=_activity(source="backdated"),
    )
    assert response.status_code == 422


async def test_backdated_workout_creates_completed_session_without_progression(session: AsyncSession, user: User):
    exercise = await _exercise(session)
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=_backdated(exercise.id),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "backdated" and body["status"] == "completed"
    assert body["progression_result"] is None and body["progression_skipped_reason"] == "no_program_inclusion"
    assert body["activity_type"] is None and body["duration_seconds"] is None
    assert body["blocks"][0]["set_logs"][0]["value"].startswith("8")
    assert body["effort"] == "4.0" and body["comment"] == "без таймера"


async def test_backdated_validation(session: AsyncSession, user: User):
    exercise = await _exercise(session)

    async def post(payload):
        return await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=payload)

    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert (await post(_backdated(exercise.id, performed_at=future))).status_code == 422
    assert (await post(_backdated(exercise.id, blocks=[]))).status_code == 422
    assert (await post(_backdated(exercise.id, program_inclusion_id=1))).status_code == 422


async def test_backdated_ownership_enforced(session: AsyncSession, user: User):
    other = await _user(session, 960263)
    foreign = await _exercise(session, owner=other)
    await session.commit()

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=_backdated(foreign.id),
    )
    assert response.status_code == 404
    missing = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=_backdated(99999999),
    )
    assert missing.status_code == 404


async def test_entries_count_in_journal_days_and_analytics(session: AsyncSession, user: User):
    user.timezone = "UTC"
    exercise = await _exercise(session)
    performed = _past(3).replace(hour=10, minute=0, second=0)
    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload=_activity(performed_at=performed.isoformat(), duration_seconds=50 * 60),
    )
    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload=_backdated(exercise.id, performed_at=performed.isoformat()),
    )

    days = await v2_get(
        session, telegram_id=user.telegram_id, path=f"/api/v2/journal/days?month={performed:%Y-%m}",
    )
    assert {d["date"]: d["count"] for d in days.json()["days"]}[f"{performed:%Y-%m-%d}"] == 2

    day = performed.date().isoformat()
    metrics = (await v2_get(
        session, telegram_id=user.telegram_id, path=f"/api/v2/analytics/training?from={day}&to={day}",
    )).json()["metrics"]
    assert metrics["total_workouts"] == 2
    assert metrics["total_minutes"] == 50  # минуты — только свободной активности
    assert metrics["without_duration"] == 1  # backdated: тренировка, но не минуты


async def test_freeform_activity_can_be_deleted_backdated_cannot(session: AsyncSession, user: User):
    exercise = await _exercise(session)
    activity = (await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=_activity(),
    )).json()
    backdated = (await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=_backdated(exercise.id),
    )).json()
    assert backdated["can_delete"] is False  # недоказанное — отказ (PROJECT_SPEC §3)

    deleted = await v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/{activity['id']}")
    assert deleted.status_code == 204
    other = await _user(session, 960264)
    foreign = await v2_delete(session, telegram_id=other.telegram_id, path=f"/api/v2/sessions/{backdated['id']}")
    assert foreign.status_code == 404


async def test_step_role_exercise_is_rejected_outside_a_program_session(session: AsyncSession, user: User):
    """#285: блок на системное STEP-упражнение (pull_ups/block_a) совпал бы с отпечатком backfill-копии
    и пропал из Журнала/дней/CSV — вне сессии программы такой блок отклоняется (422), сессия не создаётся."""
    step_a = Exercise(
        name="Блок A", metric_type=MetricType.REPS, category="pull_ups", subcategory="block_a", source_type="system",
    )
    step_b = Exercise(
        name="Блок Б", metric_type=MetricType.REPS, category="pull_ups", subcategory="block_b", source_type="system",
    )
    plain = await _exercise(session)
    session.add_all([step_a, step_b])
    await session.flush()

    for source in ("backdated", "freeform", "plan"):
        for step in (step_a, step_b):
            response = await v2_post(
                session, telegram_id=user.telegram_id, path="/api/v2/sessions",
                payload=_backdated(step.id, source=source),
            )
            assert response.status_code == 422, (source, step.subcategory, response.text)
    # Второй блок тоже проверяется (не только первый).
    mixed = _backdated(plain.id)
    mixed["blocks"].append(_backdated(step_a.id)["blocks"][0])
    mixed["blocks"][1]["sets"][0]["set_number"] = 1
    assert (await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=mixed)).status_code == 422

    listed = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    assert listed.json()["sessions"] == []
    # Обычное упражнение по-прежнему записывается.
    ok = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=_backdated(plain.id))
    assert ok.status_code == 200, ok.text
