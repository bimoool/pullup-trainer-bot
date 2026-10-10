"""Копия сессии курса — не старт MAIN (issue #307, финальное ревью; решение владельца).

Копия/повтор — ручная историческая запись: она видна в Журнале и аналитике, но не двигает отдых MAIN
(K1), счётчики инклюзии (completed_main_sessions / last_main_session_at), кредит занятий и прогрессию,
хотя несёт скопированные блоки ролей STEP. Живая сессия курса, засчитанное занятие main, строки без
source_v2 (aged/старый код) и копии legacy Workout (origin = legacy_backfill) считаются, как раньше."""

from datetime import timedelta

from sqlalchemy import select, update

from app.db.models_program import PlanItem, ProgramInclusion, SessionBlock, SetLog, TrainingSession
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import MetricType, SessionSource
from app.services.plan_convergence import PlanConvergenceService
from tests.test_services.test_plan_convergence_v2 import TODAY, WEEK4_MON, _aged_profile


async def _counters(session, inclusion_id: int) -> tuple[int | None, object]:
    inclusion = await session.get(ProgramInclusion, inclusion_id, populate_existing=True)
    return inclusion.completed_main_sessions, inclusion.last_main_session_at


async def _main(session, user_id: int) -> tuple[int, object]:
    repo = TrainingSessionRepository(session)
    return await repo.count_main_sessions(user_id), await repo.latest_main_session_at(user_id)


async def _converge(session, plan_id: int):
    _, report = await PlanConvergenceService(session).converge_user_plan(training_plan_id=plan_id, today=TODAY)
    await session.commit()
    return report


async def test_clone_of_course_session_does_not_move_convergence_counters(session):
    aged = await _aged_profile(session)
    user_id, plan_id, inclusion_id = aged["user"].id, aged["plan"].id, aged["inclusion"].id
    await _converge(session, plan_id)
    counters_before = await _counters(session, inclusion_id)
    main_before = await _main(session, user_id)
    state_before = (await session.get(ProgramInclusion, inclusion_id)).progression_state
    assert counters_before == (4, WEEK4_MON + timedelta(days=1)) and main_before == counters_before

    # копия сессии курса (блок роли STEP с подходом) ПОЗЖЕ последнего MAIN
    original = aged["current_sessions"][0]
    clone = await TrainingSessionRepository(session).clone_session(
        original, user_id=user_id, performed_at=WEEK4_MON + timedelta(days=2),
    )
    await session.commit()
    row = await session.get(TrainingSession, clone.id, populate_existing=True)
    assert row.source_v2 in ("manual_existing_workout", "manual_custom")
    assert row.plan_item_id is None and row.program_inclusion_id is None
    role_blocks = (await session.execute(
        select(SessionBlock.exercise_id).where(SessionBlock.session_id == clone.id),
    )).scalars().all()
    assert role_blocks == [aged["roles"]["block_a"].id]  # блоки ролей скопированы — и всё же не MAIN

    assert await _main(session, user_id) == main_before
    report = await _converge(session, plan_id)
    assert report.mutations == 0, report.as_dict()
    assert await _counters(session, inclusion_id) == counters_before
    assert (await session.get(ProgramInclusion, inclusion_id, populate_existing=True)).progression_state == state_before
    assert (await _converge(session, plan_id)).mutations == 0


async def test_live_course_session_still_counts_and_refreshes_counters(session):
    """Защита от пересужения: новая живая сессия курса (planned_live, блок роли с подходом) — MAIN."""
    aged = await _aged_profile(session)
    user_id, plan_id, inclusion_id = aged["user"].id, aged["plan"].id, aged["inclusion"].id
    await _converge(session, plan_id)
    count_before, _ = await _main(session, user_id)
    later = WEEK4_MON + timedelta(days=2)
    live = TrainingSession(
        user_id=user_id, source=SessionSource.PLAN, status="completed", performed_at=later,
        completed_at=later + timedelta(minutes=40), source_v2="planned_live", origin="native",
        program_inclusion_id=inclusion_id,
    )
    session.add(live)
    await session.flush()
    block = SessionBlock(session_id=live.id, order_index=0, exercise_id=aged["roles"]["block_a"].id)
    session.add(block)
    await session.flush()
    session.add(SetLog(session_block_id=block.id, set_number=1, metric_type=MetricType.REPS, value=10, unit="reps"))
    await session.commit()

    assert await _main(session, user_id) == (count_before + 1, later)
    await _converge(session, plan_id)
    assert await _counters(session, inclusion_id) == (count_before + 1, later)


async def test_credited_main_occurrence_still_counts(session):
    """Сессия, засчитавшая занятие main (plan_item_id), — MAIN и без блоков ролей."""
    aged = await _aged_profile(session)
    user_id, plan_id = aged["user"].id, aged["plan"].id
    await _converge(session, plan_id)
    count_before, _ = await _main(session, user_id)
    occurrence = (await session.execute(select(PlanItem).where(
        PlanItem.training_plan_id == plan_id, PlanItem.program_slot_key == "main", PlanItem.occurrence_index == 3,
    ))).scalars().first()
    later = WEEK4_MON + timedelta(days=2)
    credited = TrainingSession(
        user_id=user_id, source=SessionSource.PLAN, status="completed", performed_at=later,
        completed_at=later + timedelta(minutes=30), source_v2="planned_live", origin="native",
        plan_item_id=occurrence.id,
    )
    session.add(credited)
    await session.commit()
    assert await _main(session, user_id) == (count_before + 1, later)


async def test_aged_rows_keep_their_main_classification(session):
    """Aged: строки без source_v2 (как пишет код до #307) и копии legacy Workout (origin =
    legacy_backfill, source_v2 = manual_custom после миграции) по-прежнему MAIN — счётчики старых
    пользователей не уменьшаются. Отличие от копии — только origin."""
    aged = await _aged_profile(session)
    user_id = aged["user"].id
    sessions = [*aged["past_sessions"], *aged["current_sessions"]]
    rows = (await session.execute(select(TrainingSession).where(TrainingSession.id.in_(sessions)))).scalars().all()
    assert all(row.source_v2 is None for row in rows)
    assert await _main(session, user_id) == (4, WEEK4_MON + timedelta(days=1))

    await session.execute(update(TrainingSession).where(TrainingSession.id == aged["past_sessions"][0]).values(
        source_v2="manual_custom", origin="legacy_backfill",
    ))
    await session.commit()
    assert (await _main(session, user_id))[0] == 4

    # та же строка как НАТИВНАЯ ручная запись (так выглядит копия) — уже не MAIN
    await session.execute(update(TrainingSession).where(TrainingSession.id == aged["past_sessions"][0]).values(
        origin="native",
    ))
    await session.commit()
    assert (await _main(session, user_id))[0] == 3
