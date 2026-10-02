"""CRIMPD #267 — GET /api/v2/export/sessions.csv: содержимое, владение, пустая история, экранирование."""

import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models_program import SessionBlock, SessionStatus, SetLog, TrainingSession
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.multi_program import MetricType, SessionSource
from app.domain.session import BlockLog
from app.services.history_export import HEADER, sign_link, verify_link
from app.web.db import get_session
from app.web.main import app
from app.web.routes_v2_export import get_optional_init_data
from tests.test_web._v2_client import _FakeInitData, _FakeWebAppUser, v2_post
from tests.test_web._v2_client import v2_get as _v2_get
from tests.test_web.test_v2_analytics import REPS_ITEM, _add_session
from tests.test_web.test_v2_mixed_workout import _exercise, _user

PATH = "/api/v2/export/sessions.csv"


async def v2_get(session, telegram_id: int, path: str):
    app.dependency_overrides[get_optional_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )
    try:
        return await _v2_get(session, telegram_id=telegram_id, path=path)
    finally:
        app.dependency_overrides.pop(get_optional_init_data, None)


def _parse(response) -> list[list[str]]:
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


async def test_empty_history_is_header_only_with_bom(session: AsyncSession):
    user = await _user(session, 970001)
    response = await v2_get(session, telegram_id=user.telegram_id, path=PATH)
    assert _parse(response) == [HEADER]
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]


async def test_one_row_per_set_with_session_fields(session: AsyncSession):
    user = await _user(session, 970002)
    pull = await _exercise(session, "Подтягивания")
    await _add_session(session, user, datetime.now(UTC) - timedelta(hours=1), [(pull, REPS_ITEM, ["8", "7"], None)])
    rows = _parse(await v2_get(session, telegram_id=user.telegram_id, path=PATH))
    assert rows[0] == HEADER
    assert len(rows) == 3
    first, second = (dict(zip(HEADER, r, strict=True)) for r in rows[1:])
    assert (first["source"], first["exercise"], first["protocol"]) == ("v2", "Подтягивания", "reps_sets")
    assert (first["set_number"], first["value"], first["unit"]) == ("1", "8", "reps")
    assert (second["set_number"], second["value"]) == ("2", "7")


async def test_only_callers_data_is_exported(session: AsyncSession):
    mine = await _user(session, 970003)
    other = await _user(session, 970004)
    pull = await _exercise(session, "Только чужое")
    await _add_session(session, other, datetime.now(UTC) - timedelta(hours=1), [(pull, REPS_ITEM, ["5"], None)])
    response = await v2_get(session, telegram_id=mine.telegram_id, path=PATH)
    assert _parse(response) == [HEADER]
    assert "Только чужое" not in response.text


async def test_escaping_and_formula_guard(session: AsyncSession):
    user = await _user(session, 970005)
    pull = await _exercise(session, 'Тяга, "узкая"')
    training = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED,
        performed_at=datetime.now(UTC) - timedelta(hours=1), comment="=HYPERLINK(1)\nвторая строка",
        effort=Decimal("7.5"),
    )
    session.add(training)
    await session.flush()
    block = SessionBlock(session_id=training.id, order_index=0, exercise_id=pull.id)
    session.add(block)
    await session.flush()
    session.add(SetLog(
        session_block_id=block.id, set_number=1, metric_type=MetricType.REPS, value=Decimal(5), unit="reps",
        note="+1, ок",
    ))
    await session.flush()
    rows = _parse(await v2_get(session, telegram_id=user.telegram_id, path=PATH))
    row = dict(zip(HEADER, rows[1], strict=True))
    assert row["exercise"] == 'Тяга, "узкая"'  # имя из каталога (снимка нет)
    assert row["note"] == "'+1, ок"
    assert row["session_comment"] == "'=HYPERLINK(1)\nвторая строка"
    assert row["session_effort"] == "7.5"


async def test_legacy_workouts_have_source_column(session: AsyncSession):
    user = await _user(session, 970006)
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime.now(UTC) - timedelta(days=10), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    rows = [dict(zip(HEADER, r, strict=True)) for r in _parse(await v2_get(session, telegram_id=user.telegram_id, path=PATH))[1:]]
    assert len(rows) == 5
    assert {r["source"] for r in rows} == {"legacy"}
    assert [r["value"] for r in rows] == ["11", "11", "11", "4", "4"]


async def _get_raw(session: AsyncSession, path: str, headers: dict | None = None):
    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path, headers=headers or {})
    finally:
        app.dependency_overrides.clear()


async def test_signed_link_downloads_own_data_without_headers(session: AsyncSession):
    user = await _user(session, 970007)
    other = await _user(session, 970008)
    pull = await _exercise(session, "Ссылка")
    await _add_session(session, user, datetime.now(UTC) - timedelta(hours=1), [(pull, REPS_ITEM, ["6"], None)])
    created = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/export/link", payload={})
    assert created.status_code == 200
    url = created.json()["url"]
    assert "initData" not in url and "hash=" not in url
    rows = _parse(await _get_raw(session, url))
    assert len(rows) == 2 and rows[1][HEADER.index("exercise")] == "Ссылка"
    # токен другого пользователя не открывает чужие данные: подделка user_id ломает подпись
    token = url.split("token=")[1]
    forged = token.replace(f"{user.id}.", f"{other.id}.", 1)
    assert (await _get_raw(session, f"{PATH}?token={forged}")).status_code == 401


async def test_link_expired_or_garbage_and_missing_credentials_rejected(session: AsyncSession):
    user = await _user(session, 970009)
    old = sign_link(settings.bot_token, user.id, now=datetime.now(UTC).timestamp() - 3600)
    assert verify_link(settings.bot_token, old) is None
    assert (await _get_raw(session, f"{PATH}?token={old}")).status_code == 401
    assert (await _get_raw(session, f"{PATH}?token=garbage")).status_code == 401
    assert (await _get_raw(session, PATH)).status_code == 401
    assert (await _get_raw(session, PATH, {"X-Telegram-Init-Data": "bogus"})).status_code == 401


async def test_elective_note_is_readable_not_raw_json_and_hidden_after_value_edit(session: AsyncSession):
    """#283: CSV факультатива — та же читаемая строка, что в Журнале; не сырой упакованный JSON;
    после правки значения (≠ сумме подходов) разбивки нет."""
    from sqlalchemy import select

    from tests.test_web.test_v2_elective_journal import _backfilled_elective

    user = await _user(session, 970077)
    _, session_id = await _backfilled_elective(session, user)
    rows = _parse(await v2_get(session, telegram_id=user.telegram_id, path=PATH))
    elective_row = dict(zip(HEADER, rows[1], strict=True))
    assert elective_row["note"] == "Подходы: 4 · 3 · 2" and "{" not in elective_row["note"]
    assert "reps_sequence" not in "".join(",".join(r) for r in rows) and "equipment" not in "".join(",".join(r) for r in rows)

    log = await session.scalar(select(SetLog).join(SessionBlock).where(SessionBlock.session_id == session_id))
    log.value = Decimal(10)
    await session.flush()
    rows = _parse(await v2_get(session, telegram_id=user.telegram_id, path=PATH))
    assert dict(zip(HEADER, rows[1], strict=True))["note"] == ""
