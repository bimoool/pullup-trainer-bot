"""converge_user_plan (issue #304, MIGRATION_V2 §3, §5; journey J2): ОДНА идемпотентная функция сводит
план к «одна строка = одно занятие» — и на свежем, и на «старом» (aged) пользователе.

Aged-профиль строится старыми путями записи (агрегатные строки count_per_week=3 из снимка, как писал
код до #304; сессии со старой M2M-связью A+B), затем — converge. Проверяется: прошлое заморожено,
текущая неделя развёрнута с сохранением кредитов (k сессий → k засчитанных занятий по порядку),
ничего не удалено, инклюзия/прогрессия/подписка/история не тронуты, повторный прогон = 0 изменений."""

import copy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import SubscriptionStatus, User
from app.db.models_program import (
    Exercise,
    PlanItem,
    PlanWeek,
    Program,
    ProgramInclusion,
    ProgramItem,
    ProgressionStrategyProfile,
    SessionBlock,
    SessionPlanItem,
    SessionStatus,
    SetLog,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.programs import program_items_snapshot
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType, ProgramStructureType, SessionSource, WeekPhase
from app.domain.progression_strategy import ProgressionStrategyType
from app.services.plan_convergence import PlanConvergenceService
from scripts.repair_plan_convergence import run_all, run_repair

PLAN_CREATED = datetime(2026, 9, 14, 9, tzinfo=UTC)  # понедельник недели 1
TODAY = date(2026, 10, 7)  # среда недели 4 (5–11 окт)
WEEK4_MON = datetime(2026, 10, 5, 10, tzinfo=UTC)

PROGRESSED = {
    "schema_version": 1, "strategy_type": "step", "workouts_completed_in_set": 5,
    "block_a": {"target": 12, "volume": 36, "work_sets": 3, "weak_streak": 0, "stall_streak": 0},
    "block_b": {"target": 4, "volume": 16, "weak_streak": 0, "is_heavy_next": False},
}


async def _catalogue(session) -> tuple[Program, list[ProgramItem], dict[str, Exercise]]:
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step aged", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Подтягивания", goal="g", structure_type=ProgramStructureType.RECURRING, category="pull_ups",
        progression_strategy_id=profile.id, access_level="free", config={"min_rest_days": 2},
        constraints=[{"spacing_group": "main", "min_days_between_starts": 3}],
    )
    session.add(program)
    await session.flush()
    roles: dict[str, Exercise] = {}
    items: list[ProgramItem] = []
    for name, role in (("Подтягивания — объём", "block_a"), ("Подтягивания — сила", "block_b")):
        exercise = Exercise(name=name, metric_type=MetricType.REPS, category="pull_ups", subcategory=role)
        session.add(exercise)
        await session.flush()
        roles[role] = exercise
        item = ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=3, day_of_week=None,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    return program, items, roles


async def _session_linked(session, user: User, rows: list[PlanItem], performed_at: datetime, role_ex: Exercise) -> int:
    """Сессия старого кода: COMPLETED, блок роли с подходом, M2M-связь со строками (A+B)."""
    ts = TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=SessionStatus.COMPLETED,
        performed_at=performed_at, completed_at=performed_at + timedelta(minutes=40),
    )
    session.add(ts)
    await session.flush()
    block = SessionBlock(session_id=ts.id, order_index=0, exercise_id=role_ex.id)
    session.add(block)
    await session.flush()
    session.add(SetLog(
        session_block_id=block.id, set_number=1, metric_type=MetricType.REPS, value=Decimal(12), unit="reps",
    ))
    for row in rows:
        session.add(SessionPlanItem(session_id=ts.id, plan_item_id=row.id))
    await session.flush()
    return ts.id


async def _aged_profile(session) -> dict:
    """Владелецподобный aged-пользователь: курс с недели 1, агрегатные строки недель 1–4, история."""
    user = await UserRepository(session).create(telegram_id=4242, username="aged")
    user.timezone = "UTC"
    user = await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.ACTIVE, expires_at=datetime(2026, 12, 1, tzinfo=UTC),
    )
    program, program_items, roles = await _catalogue(session)
    plan = TrainingPlan(user_id=user.id, created_at=PLAN_CREATED)
    session.add(plan)
    await session.flush()
    snapshot = {
        "schema_version": 1, "program_name": "Подтягивания", "structure_type": "recurring",
        "progression_strategy_type": "step", "config": program.config,
        "exercises": [
            {"role": role, "exercise_id": ex.id, "name": ex.name, "metric_type": "reps"} for role, ex in roles.items()
        ],
        "program_items": program_items_snapshot(program_items),
    }
    inclusion = ProgramInclusion(
        training_plan_id=plan.id, program_id=program.id, snapshot=snapshot, progression_state=PROGRESSED,
        initial_progression_state={"schema_version": 1}, started_at=PLAN_CREATED, is_active=True,
    )
    session.add(inclusion)
    await session.flush()
    repo = TrainingPlanRepository(session)
    weeks: dict[int, PlanWeek] = {}
    aggregates: dict[int, list[PlanItem]] = {}
    for number in (1, 2, 3, 4):
        week = await repo.create_plan_week(
            training_plan_id=plan.id, week_number=number,
            start_date=PLAN_CREATED.date() + timedelta(weeks=number - 1), phase=WeekPhase.BASE,
        )
        weeks[number] = week
        aggregates[number] = await repo.create_plan_items_for_week_from_snapshot(
            training_plan_id=plan.id, program_inclusion_id=inclusion.id, plan_week_id=week.id,
            program_items_snapshot=snapshot["program_items"],
        )
    # История: неделя 2 — 2 сессии курса; неделя 4 — 2 сессии (Пн и Вт, обе по A+B).
    past = [
        await _session_linked(session, user, aggregates[2], datetime(2026, 9, 22 + d, 10, tzinfo=UTC), roles["block_a"])
        for d in (0, 3)
    ]
    current = [
        await _session_linked(session, user, aggregates[4], WEEK4_MON + timedelta(days=d), roles["block_a"])
        for d in (1, 0)  # порядок вставки ≠ порядок performed_at
    ]
    # Ручная строка старой формы: «Планка» 2 раза в неделю, одна сессия на неделе 4.
    plank = Exercise(name="Планка", metric_type=MetricType.TIME, category="ОФП")
    session.add(plank)
    await session.flush()
    manual = PlanItem(
        training_plan_id=plan.id, exercise_id=plank.id, count_per_week=2, plan_week_id=weeks[4].id,
    )
    session.add(manual)
    await session.flush()
    manual_session = await _session_linked(session, user, [manual], WEEK4_MON + timedelta(days=1, hours=5), plank)
    await session.commit()
    return {
        "user": user, "plan": plan, "inclusion": inclusion, "weeks": weeks, "aggregates": aggregates,
        "past_sessions": past, "current_sessions": current, "manual": manual, "manual_session": manual_session,
        "roles": roles,
    }


async def _fingerprint(session, user_id: int) -> dict:
    """История и доступ — то, что converge менять не имеет права (plan_item_id сессий — отдельно)."""
    sessions = (await session.execute(select(
        TrainingSession.id, TrainingSession.status, TrainingSession.performed_at, TrainingSession.completed_at,
        TrainingSession.source,
    ).where(TrainingSession.user_id == user_id).order_by(TrainingSession.id))).all()
    logs = (await session.execute(select(func.count()).select_from(SetLog))).scalar_one()
    links = (await session.execute(select(SessionPlanItem.session_id, SessionPlanItem.plan_item_id)
                                   .order_by(SessionPlanItem.id))).all()
    user = await session.get(User, user_id)
    access = (await session.execute(select(Program.id, Program.access_level).order_by(Program.id))).all()
    return {
        "sessions": [tuple(row) for row in sessions], "set_logs": logs, "m2m": [tuple(r) for r in links],
        "subscription": (user.subscription_status, user.subscription_expires_at), "access": [tuple(a) for a in access],
    }


async def _plan_rows(session, plan_id: int) -> list[tuple]:
    rows = (await session.execute(select(PlanItem).where(PlanItem.training_plan_id == plan_id).order_by(PlanItem.id))).scalars()
    return [
        (r.id, r.plan_week_id, r.occurrence_index, r.status, r.legacy_aggregate, r.count_per_week, r.program_slot_key)
        for r in rows
    ]


async def _credits(session, user_id: int) -> dict[int, int | None]:
    return dict((await session.execute(
        select(TrainingSession.id, TrainingSession.plan_item_id).where(TrainingSession.user_id == user_id),
    )).all())


async def test_aged_profile_converges_and_preserves_history(session):
    aged = await _aged_profile(session)
    inclusion_before = copy.deepcopy({
        "snapshot": aged["inclusion"].snapshot, "progression_state": aged["inclusion"].progression_state,
        "initial": aged["inclusion"].initial_progression_state, "started_at": aged["inclusion"].started_at,
    })
    fingerprint_before = await _fingerprint(session, aged["user"].id)
    rows_before = {row[0] for row in await _plan_rows(session, aged["plan"].id)}

    _, report = await PlanConvergenceService(session).converge_user_plan(
        training_plan_id=aged["plan"].id, today=TODAY,
    )
    await session.commit()

    assert report.mutations > 0
    # ничего не удалено
    assert rows_before <= {row[0] for row in await _plan_rows(session, aged["plan"].id)}

    # прошлые недели: агрегаты заморожены как история, видимы, своим count_per_week
    for number in (1, 2, 3):
        for row in aged["aggregates"][number]:
            await session.refresh(row)
            assert (row.legacy_aggregate, row.status, row.occurrence_index, row.count_per_week) == (True, "open", None, 3)

    # текущая неделя: агрегаты выведены (не удалены), 3 занятия main, 2 засчитаны по порядку performed_at
    for row in aged["aggregates"][4]:
        await session.refresh(row)
        assert (row.legacy_aggregate, row.status) == (True, "removed")
    week4 = aged["weeks"][4]
    occurrences = (await session.execute(select(PlanItem).where(
        PlanItem.origin_plan_week_id == week4.id, PlanItem.program_slot_key == "main",
    ).order_by(PlanItem.occurrence_index))).scalars().all()
    assert [o.occurrence_index for o in occurrences] == [1, 2, 3]
    credits = await _credits(session, aged["user"].id)
    monday, tuesday = aged["current_sessions"][1], aged["current_sessions"][0]
    assert credits[monday] == occurrences[0].id and credits[tuesday] == occurrences[1].id
    assert all(credits[s] is None for s in aged["past_sessions"])  # прошлое — кредит по старой M2M

    # ручная строка count=2 → 2 занятия; её сессия засчитала первое
    await session.refresh(aged["manual"])
    assert (aged["manual"].occurrence_index, aged["manual"].count_per_week) == (1, 1)
    copies = (await session.execute(select(PlanItem).where(
        PlanItem.origin_plan_week_id == week4.id, PlanItem.program_inclusion_id.is_(None),
    ))).scalars().all()
    assert len(copies) == 2 and credits[aged["manual_session"]] == aged["manual"].id

    # инклюзия: не пересоздана, состояние прогрессии и старт не тронуты; кэш выведен из истории
    inclusions = (await session.execute(select(ProgramInclusion))).scalars().all()
    assert len(inclusions) == 1
    inclusion = inclusions[0]
    await session.refresh(inclusion)
    assert inclusion.progression_state == inclusion_before["progression_state"]
    assert inclusion.initial_progression_state == inclusion_before["initial"]
    assert inclusion.started_at == inclusion_before["started_at"]
    assert inclusion.snapshot == inclusion_before["snapshot"]
    assert (inclusion.status, inclusion.sequence_cursor, inclusion.completed_main_sessions) == ("active", 4, 4)
    assert inclusion.last_main_session_at == WEEK4_MON + timedelta(days=1)

    # история, подписка и доступ — без изменений
    assert await _fingerprint(session, aged["user"].id) == fingerprint_before

    # повторный прогон — ноль изменений
    rows_after_first = await _plan_rows(session, aged["plan"].id)
    credits_after_first = await _credits(session, aged["user"].id)
    _, again = await PlanConvergenceService(session).converge_user_plan(training_plan_id=aged["plan"].id, today=TODAY)
    await session.commit()
    assert again.mutations == 0, again.as_dict()
    assert await _plan_rows(session, aged["plan"].id) == rows_after_first
    assert await _credits(session, aged["user"].id) == credits_after_first


async def test_aged_profile_current_and_future_plan_stays_functional(session):
    """J2: после сходимости план работает: «2 из 3» текущей недели, next — available с Пт (Вт + 3)."""
    import uuid

    from app.web import routes_v2
    from tests.test_web._v2_client import v2_get, v2_post

    aged = await _aged_profile(session)
    routes_v2_now = datetime(2026, 10, 7, 12, tzinfo=UTC)
    original = routes_v2._utcnow
    routes_v2._utcnow = lambda: routes_v2_now
    try:
        plan = (await v2_get(session, aged["user"].telegram_id, "/api/v2/plan")).json()["plan"]
        await v2_post(session, aged["user"].telegram_id, "/api/v2/plan/weeks", {"week_number": 5})
        plan = (await v2_get(session, aged["user"].telegram_id, "/api/v2/plan")).json()["plan"]
    finally:
        routes_v2._utcnow = original
    week_id = {w["week_number"]: w["id"] for w in plan["plan_weeks"]}
    summary = {s["plan_week_id"]: s for s in plan["week_summaries"]}
    assert (summary[week_id[4]]["planned"], summary[week_id[4]]["completed"]) == (5, 3)  # 3 main + 2 ручных
    assert (summary[week_id[2]]["planned"], summary[week_id[2]]["completed"]) == (6, 4)  # legacy-агрегаты A и B
    main4 = sorted(
        (i for i in plan["plan_items"] if i["plan_week_id"] == week_id[4] and i["program_slot_key"] == "main"),
        key=lambda i: i["occurrence_index"],
    )
    assert [i["state"] for i in main4] == ["completed", "completed", "too_early"]
    assert main4[2]["available_from"] == "2026-10-09"
    future = [i for i in plan["plan_items"] if i["plan_week_id"] == week_id[5]]
    assert len(future) == 3 and all(i["occurrence_index"] for i in future)
    started = await v2_post(session, aged["user"].telegram_id, "/api/v2/sessions/live", {
        "client_session_id": str(uuid.uuid4()), "plan_item_ids": [future[0]["id"]],
    })
    assert started.status_code == 409 and started.json()["detail"]["code"] == "too_early"


async def test_fresh_inclusion_converges_to_occurrences_and_second_run_is_noop(session):
    user = await UserRepository(session).create(telegram_id=5151, username="fresh")
    program, _, _ = await _catalogue(session)
    plan = TrainingPlan(user_id=user.id, created_at=WEEK4_MON)
    session.add(plan)
    await session.flush()
    from app.services.program_inclusion import ProgramInclusionRequest, ProgramInclusionService

    inclusion = await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )
    assert [s["key"] for s in inclusion.snapshot["slots"]] == ["main"]
    _, first = await PlanConvergenceService(session).converge_user_plan(training_plan_id=plan.id, today=TODAY)
    rows = await _plan_rows(session, plan.id)
    assert [(r[2], r[6]) for r in rows] == [(1, "main"), (2, "main"), (3, "main")]
    assert first.occurrences_created == 3
    _, second = await PlanConvergenceService(session).converge_user_plan(training_plan_id=plan.id, today=TODAY)
    assert second.mutations == 0


async def test_missing_current_rows_and_repaired_snapshot_are_generated(session):
    """Aged-случай #301: снимок без program_items и ни одной строки в текущей неделе."""
    aged = await _aged_profile(session)
    inclusion = aged["inclusion"]
    inclusion.snapshot = {k: v for k, v in inclusion.snapshot.items() if k != "program_items"}
    for row in aged["aggregates"][4]:
        await session.delete(row)
    await session.commit()

    _, report = await PlanConvergenceService(session).converge_user_plan(training_plan_id=aged["plan"].id, today=TODAY)
    await session.commit()
    assert report.snapshot_repairs == 1
    main = (await session.execute(select(PlanItem.occurrence_index).where(
        PlanItem.origin_plan_week_id == aged["weeks"][4].id, PlanItem.program_slot_key == "main",
    ).order_by(PlanItem.occurrence_index))).scalars().all()
    assert main == [1, 2, 3]
    _, again = await PlanConvergenceService(session).converge_user_plan(training_plan_id=aged["plan"].id, today=TODAY)
    assert again.mutations == 0


async def test_no_auto_enrol_and_removed_course_is_not_regenerated(session):
    aged = await _aged_profile(session)
    aged["inclusion"].is_active = False
    await session.commit()
    _, _report = await PlanConvergenceService(session).converge_user_plan(training_plan_id=aged["plan"].id, today=TODAY)
    await session.commit()
    main = (await session.execute(select(func.count()).select_from(PlanItem).where(
        PlanItem.program_slot_key.is_not(None),
    ))).scalar_one()
    assert main == 0  # снятый курс не генерирует занятий (ручная строка развёрнута — она не курс)
    assert (await session.execute(select(func.count()).select_from(ProgramInclusion))).scalar_one() == 1
    for row in aged["aggregates"][4]:
        await session.refresh(row)
        assert (row.legacy_aggregate, row.status) == (False, "open")  # строки снятого курса — как были


async def test_guarded_repair_script_on_aged_profile_then_noop(session):
    aged = await _aged_profile(session)
    telegram_id = aged["user"].telegram_id  # ORM-объекты истекают после rollback/commit внутри скрипта
    code, report = await run_repair(session, telegram_id=telegram_id, apply=False, today=TODAY)
    assert code == 0 and report["guard_violations"] == [], report["guard_violations"]
    assert report["result"] == "dry-run: rolled back, nothing written"
    assert len(report["mutation"]["session_credits_linked"]) == 3

    code, report = await run_repair(session, telegram_id=telegram_id, apply=True, today=TODAY)
    assert code == 0 and report["result"] == "applied", report["guard_violations"]
    code, report = await run_repair(session, telegram_id=telegram_id, apply=True, today=TODAY)
    assert code == 0 and report["result"] == "nothing to do", report["mutation"]


async def test_run_all_second_apply_has_zero_mutations(session, test_dsn):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    await _aged_profile(session)
    engine = create_async_engine(test_dsn)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        code, dry = await run_all(apply=False, today=TODAY, session_factory=factory)
        assert code == 0 and dry["total_mutations"] > 0
        code, applied = await run_all(apply=True, today=TODAY, session_factory=factory)
        assert code == 0 and applied["total_mutations"] == dry["total_mutations"]
        code, again = await run_all(apply=True, today=TODAY, session_factory=factory)
        assert code == 0 and again["total_mutations"] == 0, again
    finally:
        await engine.dispose()


async def test_course_without_materializable_slots_keeps_its_rows_startable(session):
    """Регрессия (найдено E2E #304): синтетический STEP-курс без ProgramItem (строки PlanItem заведены
    напрямую, как scripts/e2e_seed.py::seed_v2_session_ready) — занятий на замену нет, значит агрегатные
    строки НЕ выводятся из плана и стартуются как раньше; повторная сходимость — 0 изменений."""
    import uuid

    from app.services.program_inclusion import ProgramInclusionRequest, ProgramInclusionService
    from app.web import routes_v2
    from tests.test_web._v2_client import v2_get, v2_post

    user = await UserRepository(session).create(telegram_id=6161, username="synthetic")
    user = await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.TRIAL, expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step synth", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="E2E Live Session", goal="e2e", structure_type=ProgramStructureType.RECURRING, category="synth_304",
        progression_strategy_id=profile.id, config={"block_a": {"base_target": 10, "work_sets": 3}},
    )
    session.add(program)
    await session.flush()
    session.add_all([
        Exercise(name="Блок A", metric_type=MetricType.REPS, category="synth_304", subcategory="block_a"),
        Exercise(name="Блок Б", metric_type=MetricType.REPS, category="synth_304", subcategory="block_b"),
    ])
    await session.flush()
    inclusion = await ProgramInclusionService(session).create_inclusion(
        user_id=user.id, request=ProgramInclusionRequest(program_id=program.id),
    )
    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    rows = []
    for item in inclusion.snapshot["exercises"]:
        row = PlanItem(
            training_plan_id=plan.id, exercise_id=item["exercise_id"], count_per_week=3,
            program_inclusion_id=inclusion.id,
        )
        session.add(row)
        rows.append(row)
    await session.commit()

    original = routes_v2._utcnow
    routes_v2._utcnow = lambda: datetime.now(UTC)
    try:
        listed = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]["plan_items"]
    finally:
        routes_v2._utcnow = original
    assert sorted(i["id"] for i in listed) == sorted(r.id for r in rows)
    assert all(i["status"] == "open" and not i["legacy_aggregate"] for i in listed)
    started = await v2_post(session, user.telegram_id, "/api/v2/sessions/live", {
        "client_session_id": str(uuid.uuid4()), "plan_item_ids": [r.id for r in rows],
    })
    assert started.status_code == 200, started.text
    assert len(started.json()["blocks"]) == 2
    _, again = await PlanConvergenceService(session).converge_user_plan(
        training_plan_id=plan.id, today=datetime.now(UTC).date(),
    )
    assert again.mutations == 0, again.as_dict()

