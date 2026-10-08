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

issue #304: неделя курса — 3 занятия (одна строка = одно занятие), не 2 агрегатные строки A/Б.

Починка (решение владельца 2026-10-06): PlanWeekService.converge_inclusion_snapshot дополняет ТОЛЬКО
отсутствующий/пустой program_items активной инклюзии из live Program, громко в лог, идемпотентно; непустой
исторический снимок, progression_state, started_at, прошлые PlanItem и сессии не трогаются. Раньше эти
тесты были xfail(strict=True) — маркер снят вместе с починкой (откат починки возвращает их в красное).
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

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
    TrainingSession,
)
from app.db.repositories.programs import program_items_snapshot
from app.db.repositories.training_sessions import SessionBlockInput, SetLogInput
from app.domain.multi_program import MetricType, ProgramStructureType, SessionSource, WeekPhase
from app.services.plan_week import PlanWeekService
from app.services.session_log import TrainingSessionLogService
from app.web import routes_v2
from scripts.backfill_multi_program import normalize_legacy_snapshots
from tests.test_web._v2_client import v2_get, v2_post

TG = 1001
PLAN_CREATED = datetime(2026, 9, 14, 10, tzinfo=UTC)  # понедельник недели 1; 6 окт 2026 = неделя 4 (5–11 окт)
ADDED_AT = datetime(2026, 9, 14, 11, tzinfo=UTC)
OPENED_IN_WEEK_1 = datetime(2026, 9, 16, 11, tzinfo=UTC)
TODAY = datetime(2026, 10, 6, 11, tzinfo=UTC)

# Историческое состояние прогрессии «как у владельца»: значения произвольные, важна только их неизменность.
PROGRESSED_STATE = {
    "schema_version": 1, "strategy_type": "step", "workouts_completed_in_set": 2,
    "block_a": {"target": 11, "volume": 33, "work_sets": 3, "weak_streak": 0, "stall_streak": 0},
    "block_b": {"target": 4, "volume": 12, "weak_streak": 0, "is_heavy_next": True},
}
REPAIR_EVENT = "plan_convergence_repair"


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
    assert len(_current_week_items(plan)) == 3


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
    assert len(_current_week_items(plan)) == 3


async def _legacy_owner_like_state(session, user: User, clock) -> tuple[Program, list[ProgramItem], ProgramInclusion]:
    """Как у владельца на staging (снимок 2026-10-06): курс подключён в неделе 1, неделя 1 открывалась и
    материализована, в ней есть завершённая сессия, прогрессия ушла вперёд; снимок — формы legacy-бэкфилла
    (ключа program_items нет). Недели 2–3 не открывались, сегодня — неделя 4."""
    await _plan_created_in_september(session, user)
    program, items = await _program(session, with_items=True)
    inclusion_id = await _add_course(session, clock, program)
    week_1 = _current_week_items(await _get_plan(session, clock, OPENED_IN_WEEK_1))
    assert len(week_1) == 3  # #304: курс (пул A+Б × 3) = 3 занятия
    inclusion = await session.get(ProgramInclusion, inclusion_id)
    inclusion.snapshot = {k: v for k, v in inclusion.snapshot.items() if k != "program_items"}
    inclusion.progression_state = PROGRESSED_STATE
    await session.commit()
    await TrainingSessionLogService(session).record_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=OPENED_IN_WEEK_1, effort=None, comment=None,
        program_inclusion_id=inclusion_id, completed_at=OPENED_IN_WEEK_1,
        blocks=[SessionBlockInput(exercise_id=items[0].exercise_id, sets=[
            SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(8), unit="reps"),
        ])],
    )
    await session.commit()
    return program, items, inclusion


async def test_aged_legacy_snapshot_converges_and_preserves_history_progression_and_identity(
    session, user: User, clock, caplog,
):
    """Приёмка владельца (локальная копия staging-формы): после GET /plan в неделе 4 — строки курса; снимок
    получил валидные program_items; started_at/progression/is_active/прочие ключи снимка, строки недели 1 и
    завершённая сессия не изменились; починка залогирована громко и ровно один раз (идемпотентность)."""
    _program, items, inclusion = await _legacy_owner_like_state(session, user, clock)
    snapshot_before = dict(inclusion.snapshot)
    started_at_before = inclusion.started_at
    week_1_items_before = {
        (item.id, item.plan_week_id) for item in (await session.execute(select(PlanItem))).scalars()
    }
    sessions_before = [(s.id, s.status) for s in (await session.execute(select(TrainingSession))).scalars()]
    assert len(sessions_before) == 1

    with caplog.at_level(logging.WARNING, logger="app.services.plan_week"):
        plan = await _get_plan(session, clock, TODAY)

    assert _current_week_number(plan) == 4
    assert len(_current_week_items(plan)) == 3
    await session.refresh(inclusion)
    assert inclusion.snapshot["program_items"] == program_items_snapshot(items)
    assert {k: v for k, v in inclusion.snapshot.items() if k != "program_items"} == snapshot_before
    assert inclusion.progression_state == PROGRESSED_STATE
    assert inclusion.started_at == started_at_before
    assert inclusion.is_active
    after = {(item.id, item.plan_week_id) for item in (await session.execute(select(PlanItem))).scalars()}
    assert week_1_items_before <= after  # исторические строки недели 1 на месте и в своей неделе
    assert [(s.id, s.status) for s in (await session.execute(select(TrainingSession))).scalars()] == sessions_before
    repairs = [r for r in caplog.records if r.getMessage().startswith(REPAIR_EVENT)]
    assert len(repairs) == 1
    assert repairs[0].levelno == logging.WARNING
    assert repairs[0].inclusion_id == inclusion.id
    assert repairs[0].reason == "missing_program_items_key"

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.services.plan_week"):
        again = await _get_plan(session, clock, TODAY)
    assert len(_current_week_items(again)) == 3  # без дублей
    assert not [r for r in caplog.records if r.getMessage().startswith(REPAIR_EVENT)]


async def test_non_empty_historical_snapshot_is_never_overwritten_from_live_program(session, user: User, clock):
    """Решение владельца №2: непустой снимок — исторический факт; новый ProgramItem живой Program не попадает
    ни в снимок, ни в строки недели 4 этого пользователя."""
    await _plan_created_in_september(session, user)
    program, _ = await _program(session, with_items=True)
    inclusion_id = await _add_course(session, clock, program)
    await _get_plan(session, clock, OPENED_IN_WEEK_1)
    inclusion = await session.get(ProgramInclusion, inclusion_id)
    snapshot_before = dict(inclusion.snapshot)
    extra = Exercise(name="Новое упражнение курса", metric_type=MetricType.REPS, category="pull_ups")
    session.add(extra)
    await session.flush()
    session.add(ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=extra.id, count_per_week=1))
    await session.commit()

    assert await PlanWeekService(session).converge_inclusion_snapshot(inclusion) is None
    plan = await _get_plan(session, clock, TODAY)

    await session.refresh(inclusion)
    assert inclusion.snapshot == snapshot_before
    assert len(_current_week_items(plan)) == 3
    assert extra.id not in {item["exercise_id"] for item in _current_week_items(plan)}


async def test_inactive_inclusion_snapshot_is_not_repaired(session, user: User, clock):
    await _plan_created_in_september(session, user)
    program, _ = await _program(session, with_items=True)
    inclusion = await session.get(ProgramInclusion, await _add_course(session, clock, program))
    inclusion.snapshot = {k: v for k, v in inclusion.snapshot.items() if k != "program_items"}
    inclusion.is_active = False
    await session.commit()

    assert await PlanWeekService(session).converge_inclusion_snapshot(inclusion) is None
    assert "program_items" not in inclusion.snapshot


async def test_unrepairable_gap_is_logged_loudly_not_silently_skipped(session, user: User, clock, caplog):
    """Live Program без ProgramItem: чинить нечем — снимок не трогаем, GET /plan не падает, gap в логе."""
    await _plan_created_in_september(session, user)
    program, _ = await _program(session, with_items=False)
    inclusion_id = await _add_course(session, clock, program)

    with caplog.at_level(logging.WARNING, logger="app.services.plan_week"):
        plan = await _get_plan(session, clock, TODAY)

    assert _current_week_items(plan) == []
    assert (await session.get(ProgramInclusion, inclusion_id)).snapshot["program_items"] == []
    gaps = [r for r in caplog.records if r.getMessage().startswith("plan_convergence_gap")]
    assert gaps and all(r.levelno == logging.WARNING for r in gaps)
    assert not [r for r in caplog.records if r.getMessage().startswith(REPAIR_EVENT)]


async def test_h2_legacy_backfill_snapshot_without_program_items_converges_on_current_week(session, user: User, clock):
    """H2b/H3: инклюзия со снимком без program_items (legacy backfill до checkpoint 1.1), неделя 1 уже открывалась
    (строки привязаны к ней), недели 2–3 пропущены. Сегодня, на неделе 4, пользователь ждёт строки курса."""
    await _plan_created_in_september(session, user)
    program, _ = await _program(session, with_items=True)
    inclusion_id = await _add_course(session, clock, program)
    assert len(_current_week_items(await _get_plan(session, clock, OPENED_IN_WEEK_1))) == 3
    inclusion = await session.get(ProgramInclusion, inclusion_id)
    inclusion.snapshot = {k: v for k, v in inclusion.snapshot.items() if k != "program_items"}
    await session.commit()

    plan = await _get_plan(session, clock, TODAY)

    assert _current_week_number(plan) == 4
    assert len(_current_week_items(plan)) == 3  # сейчас 0 -> «0 из 0 · На эту неделю пока ничего не запланировано»


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

    assert len(_current_week_items(plan)) == 3  # сейчас 0
    assert (await session.execute(select(PlanItem).where(PlanItem.plan_week_id.is_(None)))).scalars().all() == []
    assert (await session.execute(select(PlanWeek))).scalars().all()  # недели созданы, строк нет
