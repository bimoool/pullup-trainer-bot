"""Recovery campaign, role C: сходимость «старых» состояний плана (docs/STAGING_FUNCTIONAL_REACHABILITY.md).

Свежий пользователь проходит #301, а реальный staging-пользователь, подключивший «Подтягивания»
в середине сентября, видит «Week 4 · Текущая неделя · 0 из 0». Причина — не гонка и не таймзона:
PlanWeekService материализует будущую/текущую неделю ТОЛЬКО из inclusion.snapshot["program_items"]
(app/services/plan_week.py::_materialize_inclusions_into_week), а у инклюзий, созданных старым кодом,
этого списка нет (legacy backfill до checkpoint 1.1) либо он пуст (Program на момент подключения была
без ProgramItem). Строки недели 1 при этом уже привязаны, так что «unweeked»-ветка тоже не срабатывает.

Состояние строится настоящими путями: POST /program-inclusions и GET /plan (с подменой «сейчас»),
PlanWeekService, normalize_legacy_snapshots. Единственная «ручная» операция — приведение снимка к
формату, который писал старый backfill (ключа program_items нет), как в
tests/test_scripts/test_backfill_multi_program.py::test_legacy_snapshot_without_program_items_gets_normalized;
PlanItem'ы назначения не вставляются руками.

xfail(strict=True): тесты описывают ПРАВИЛЬНОЕ поведение (в текущей неделе есть строки курса) и
перевернутся в XPASS-ошибку, когда починка появится — тогда маркер надо снять.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import User
from app.db.models_program import (
    Exercise,
    PlanItem,
    PlanWeek,
    Program,
    ProgramInclusion,
    ProgramItem,
    TrainingPlan,
)
from app.db.repositories.programs import program_items_snapshot
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.web import routes_v2
from scripts.backfill_multi_program import normalize_legacy_snapshots
from tests.test_web._v2_client import v2_get, v2_post

TG = 1001
PLAN_CREATED = datetime(2026, 9, 14, 10, tzinfo=UTC)  # понедельник недели 1; 6 окт 2026 = неделя 4 (5–11 окт)
ADDED_AT = datetime(2026, 9, 14, 11, tzinfo=UTC)
OPENED_IN_WEEK_1 = datetime(2026, 9, 16, 11, tzinfo=UTC)
TODAY = datetime(2026, 10, 6, 11, tzinfo=UTC)

XFAIL = pytest.mark.xfail(
    strict=True, reason="recovery campaign: aged-state convergence, see docs/STAGING_FUNCTIONAL_REACHABILITY.md",
)


@pytest.fixture
def clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
    return _set


async def _program(session, *, with_items: bool) -> tuple[Program, list[ProgramItem]]:
    program = Program(
        name="Подтягивания", goal="test", structure_type=ProgramStructureType.RECURRING, category="pull_ups", config={},
    )
    session.add(program)
    await session.flush()
    items: list[ProgramItem] = []
    if with_items:
        items = await _add_program_items(session, program)
    await session.commit()
    return program, items


async def _add_program_items(session, program: Program) -> list[ProgramItem]:
    """То, что миграция a4c8e1f7b2d9 (#296) сделала с живой Program при деплое 2026-10-05."""
    items = []
    for subcategory in ("block_a", "block_b"):
        exercise = Exercise(
            name=f"Подтягивания {subcategory}", metric_type=MetricType.REPS, category="pull_ups",
            subcategory=subcategory,
        )
        session.add(exercise)
        await session.flush()
        item = ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=3,
            day_of_week=None,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    return items


async def _plan_created_in_september(session, user: User) -> TrainingPlan:
    plan = TrainingPlan(user_id=user.id, created_at=PLAN_CREATED)
    session.add(plan)
    await session.commit()
    return plan


async def _add_course(session, clock, program: Program) -> int:
    clock(ADDED_AT)
    response = await v2_post(session, TG, "/api/v2/program-inclusions", {"program_id": program.id})
    assert response.status_code == 200, response.text
    await session.commit()
    return response.json()["id"]


async def _get_plan(session, clock, now: datetime) -> dict:
    clock(now)
    response = await v2_get(session, TG, "/api/v2/plan")
    assert response.status_code == 200, response.text
    await session.commit()
    return response.json()["plan"]


def _current_week_items(plan: dict) -> list[dict]:
    return [item for item in plan["plan_items"] if item["plan_week_id"] == plan["current_week_id"]]


def _current_week_number(plan: dict) -> int:
    return next(week["week_number"] for week in plan["plan_weeks"] if week["id"] == plan["current_week_id"])


async def test_control_fresh_course_added_in_september_has_rows_in_week_4(session, user: User, clock):
    """H1 (контроль, зелёный): курс подключён 14 сентября через текущий код и ни разу не открывался."""
    await _plan_created_in_september(session, user)
    program, _ = await _program(session, with_items=True)
    await _add_course(session, clock, program)

    plan = await _get_plan(session, clock, TODAY)

    assert _current_week_number(plan) == 4
    assert len(_current_week_items(plan)) == 2


async def test_control_rerunning_backfill_normalization_heals_legacy_snapshot(session, user: User, clock):
    """H2c (контроль, зелёный): единственный сегодняшний путь лечения — повторный прогон backfill-скрипта."""
    await _plan_created_in_september(session, user)
    program, items = await _program(session, with_items=True)
    inclusion_id = await _add_course(session, clock, program)
    await _get_plan(session, clock, OPENED_IN_WEEK_1)
    inclusion = await session.get(ProgramInclusion, inclusion_id)
    inclusion.snapshot = {k: v for k, v in inclusion.snapshot.items() if k != "program_items"}  # формат старого backfill
    await session.commit()

    assert await normalize_legacy_snapshots(
        session, program_id=program.id, program_items_snap=program_items_snapshot(items),
    ) == 1
    await session.commit()

    plan = await _get_plan(session, clock, TODAY)
    assert len(_current_week_items(plan)) == 2


@XFAIL
async def test_h2_legacy_backfill_snapshot_without_program_items_converges_on_current_week(session, user: User, clock):
    """H2b/H3: инклюзия со снимком без program_items (legacy backfill до checkpoint 1.1), неделя 1 уже открывалась
    (строки привязаны к ней), недели 2–3 пропущены. Сегодня, на неделе 4, пользователь ждёт строки курса."""
    await _plan_created_in_september(session, user)
    program, _ = await _program(session, with_items=True)
    inclusion_id = await _add_course(session, clock, program)
    assert len(_current_week_items(await _get_plan(session, clock, OPENED_IN_WEEK_1))) == 2
    inclusion = await session.get(ProgramInclusion, inclusion_id)
    inclusion.snapshot = {k: v for k, v in inclusion.snapshot.items() if k != "program_items"}
    await session.commit()

    plan = await _get_plan(session, clock, TODAY)

    assert _current_week_number(plan) == 4
    assert len(_current_week_items(plan)) == 2  # сейчас 0 -> «0 из 0 · На эту неделю пока ничего не запланировано»


@XFAIL
async def test_h3_course_added_while_program_had_no_program_items_converges_after_items_appear(
    session, user: User, clock,
):
    """H3b: Program «Подтягивания» была без ProgramItem (старый seed_catalog), снимок получил program_items=[];
    миграция #296 (2026-10-05) добавила ProgramItem в живую Program. Курс должен наполниться."""
    await _plan_created_in_september(session, user)
    program, _ = await _program(session, with_items=False)
    inclusion_id = await _add_course(session, clock, program)
    assert (await session.get(ProgramInclusion, inclusion_id)).snapshot["program_items"] == []
    assert _current_week_items(await _get_plan(session, clock, OPENED_IN_WEEK_1)) == []
    await _add_program_items(session, program)
    await session.commit()

    plan = await _get_plan(session, clock, TODAY)

    assert len(_current_week_items(plan)) == 2  # сейчас 0
    assert (await session.execute(select(PlanItem).where(PlanItem.plan_week_id.is_(None)))).scalars().all() == []
    assert (await session.execute(select(PlanWeek))).scalars().all()  # недели созданы, строк нет
