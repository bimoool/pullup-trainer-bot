"""#284 (исправление #282) → #308 — нативная копия legacy Workout (origin = legacy_backfill) не дублируется
в Журнале v2 (её показывает legacy-карточка с «Изменить»/«Удалить»), а в итогах (календарь, Профиль,
Аналитика) входит в canonical_sessions РОВНО ОДИН раз. Скрытие — по явному origin, не по отпечатку;
замещённая (superseded) копия удалённой legacy-записи не показывается и не считается нигде.

Копии создаются НАСТОЯЩЕЙ функцией сведения (dual-write писателей старой схемы и scripts/backfill_multi_program.py
делят одну реализацию — LegacyConvergenceRepository), чтобы тест ломался, если они разойдутся."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ElectiveWorkout, Workout
from app.db.models_program import (
    Exercise,
    PlanItem,
    SessionPlanItem,
    SessionStatus,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.training_sessions import (
    SessionBlockInput,
    SetLogInput,
    TrainingSessionRepository,
)
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.multi_program import MetricType, SessionSource
from app.domain.session import BlockLog
from scripts.backfill_multi_program import (
    _EXERCISE_BLOCK_A_NAME,
    _EXERCISE_BLOCK_B_NAME,
    _create_training_session_for_elective,
    _create_training_session_for_workout,
    _get_or_create_exercise,
)
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch

BASE = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
FROM_TO = "date_from=2026-10-01&date_to=2026-10-31"


async def _legacy_user(session: AsyncSession, telegram_id: int):
    user = await UserRepository(session).create(telegram_id=telegram_id, username=f"u{telegram_id}")
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=BASE - timedelta(days=30), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    return user, workout_set


def _kwargs(user, workout_set, at: datetime, max_a: int):
    return {
        "user_id": user.id, "workout_set_id": workout_set.id, "performed_at": at,
        "block_a_reps": BlockLog(working_reps=(10, 10, 10), max_reps=max_a),
        "block_b_reps": BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        "block_a_equipment_type": EquipmentType.BAND, "block_a_equipment_value": Decimal("15.0"),
        "block_b_equipment_type": EquipmentType.BAND, "block_b_equipment_value": Decimal("15.0"),
    }


async def _free_workout(session, user, workout_set, at: datetime, max_a: int) -> Workout:
    return await WorkoutRepository(session).record_free_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=at,
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=max_a),
        equipment_type=EquipmentType.BAND, equipment_value=Decimal("15.0"),
    )


async def _backfill(session: AsyncSession, workouts: list[Workout]) -> None:
    """То же, что backfill_all делает с историей пользователя (минус общий каталог программ)."""
    exercise_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    exercise_b = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_B_NAME, subcategory="block_b")
    for workout in workouts:
        await _create_training_session_for_workout(
            session, workout, exercise_a_id=exercise_a.id, exercise_b_id=exercise_b.id,
        )
    await session.flush()


async def _history(session, telegram_id: int) -> list[dict]:
    """Legacy-карточки Журнала (GET /api/history, как их грузит HistoryScreen) — без каких-либо флагов."""
    response = await v2_get(session, telegram_id=telegram_id, path=f"/api/history?{FROM_TO}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def _journal_v2(session, telegram_id: int, *, limit: int = 50, offset: int = 0, status: str | None = "completed",
                      hide: bool = True) -> dict:
    """Журнал v2 (GET /api/v2/sessions) так, как его грузит useJournalV2: completed + месяц + exclude_backfilled."""
    query = f"limit={limit}&offset={offset}&{FROM_TO}"
    if status is not None:
        query += f"&status={status}"
    if hide:
        query += "&exclude_backfilled=true"
    response = await v2_get(session, telegram_id=telegram_id, path=f"/api/v2/sessions?{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _maxes(items: list[dict]) -> list[str]:
    return [item["result_a"] for item in items]


async def _migrated_user(session: AsyncSession, telegram_id: int):
    """Каскадная (макс. 11) + задним числом (12) + свободная (13), все перенесены; затем
    пост-миграционная legacy-запись (14): с #308 dual-write даёт ей нативную копию сразу (раньше v2-копии
    у неё не было, и Аналитика/Журнал/Профиль расходились, D14)."""
    user, workout_set = await _legacy_user(session, telegram_id)
    repo = WorkoutRepository(session)
    await repo.record_workout(**_kwargs(user, workout_set, BASE, 11))
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=1), 12))
    await _free_workout(session, user, workout_set, BASE + timedelta(hours=2), 13)
    await _backfill(session, await repo.list_for_user(user.id))
    post = await repo.record_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=3), 14))
    return user, workout_set, post


def _edit_payload(max_a: int) -> dict:
    return {
        "block_a_working_reps": [10, 10, 10], "block_a_max_reps": max_a,
        "block_b_working_reps": [3, 3, 3, 3], "block_b_max_reps": 3, "confirm_anomalies": True,
    }


async def test_journal_hides_backfill_copies_and_legacy_shows_every_card_with_actions(session: AsyncSession):
    user, _workout_set, post = await _migrated_user(session, 982001)

    # Журнал v2 не содержит ни одной копии legacy Workout (все четыре записи показаны legacy-карточками)
    page = await _journal_v2(session, user.telegram_id)
    assert page["sessions"] == [] and page["has_more"] is False

    # legacy-история отдаёт ВСЕ четыре записи (и перенесённые тоже) с действиями
    items = await _history(session, user.telegram_id)
    assert len(items) == 4
    assert items[0]["workout_id"] == post.id
    assert all(item["is_deletable"] for item in items)
    assert items[0]["target_a"] is not None  # цель следующей тренировки — на самой свежей, как до #282
    assert all(item["target_a"] is None for item in items[1:])
    # без флага ответ /sessions — все canonical-копии на месте (SessionJournalScreen): 4 записи = 4 копии
    assert len((await _journal_v2(session, user.telegram_id, hide=False))["sessions"]) == 4
    # скрытие — только отображение: ни одна запись не изменена и не удалена; копия у КАЖДОЙ legacy-строки
    assert await session.scalar(select(func.count()).select_from(Workout).where(Workout.user_id == user.id)) == 4
    assert await session.scalar(
        select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id),
    ) == 4


async def test_history_endpoint_ignores_legacy_exclude_migrated_param(session: AsyncSession):
    """Старый клиент (#282) шлёт &exclude_migrated=true — параметр больше ничего не скрывает."""
    user, _workout_set, _post = await _migrated_user(session, 982002)

    response = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/history?{FROM_TO}&exclude_migrated=true")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 4


async def test_legacy_edit_after_migration_is_visible(session: AsyncSession):
    """Правка перенесённой legacy-записи (PATCH /api/history, как «✏️ Изменить») видна в Журнале;
    устаревшая v2-копия по-прежнему скрыта."""
    user, _workout_set, _post = await _migrated_user(session, 982003)
    migrated = next(i for i in await _history(session, user.telegram_id) if "максимум 12" in i["result_a"])

    response = await v2_patch(
        session, user.telegram_id, f"/api/history/{migrated['workout_id']}", _edit_payload(max_a=17),
    )
    assert response.status_code == 200, response.text

    items = await _history(session, user.telegram_id)
    assert sum("максимум 17" in i["result_a"] for i in items) == 1
    assert sum("максимум 12" in i["result_a"] for i in items) == 0
    assert (await _journal_v2(session, user.telegram_id))["sessions"] == []  # копия в Журнале v2 не дублируется
    # #308: правка legacy-записи обновила и её копию (revision + 1), а не оставила устаревшую
    copy = await session.scalar(
        select(TrainingSession).where(TrainingSession.user_id == user.id, TrainingSession.legacy_id == migrated["workout_id"]),
    )
    assert copy is not None and copy.revision == 1


async def test_legacy_delete_supersedes_the_native_copy_everywhere(session: AsyncSession):
    user, _workout_set, _post = await _migrated_user(session, 982004)
    migrated = next(i for i in await _history(session, user.telegram_id) if "максимум 12" in i["result_a"])

    response = await v2_delete(session, user.telegram_id, f"/api/history/{migrated['workout_id']}")
    assert response.status_code == 200, response.text

    items = await _history(session, user.telegram_id)
    assert len(items) == 3 and sum("максимум 12" in i["result_a"] for i in items) == 0
    # #308: копия удалённой записи ЗАМЕЩЕНА (строка остаётся — архивировать, не удалять), её нет ни в
    # списке Журнала, ни в календаре, ни в Профиле
    assert await session.scalar(
        select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id),
    ) == 4
    assert await session.scalar(
        select(func.count()).select_from(TrainingSession).where(
            TrainingSession.user_id == user.id, TrainingSession.superseded_at.is_not(None),
            TrainingSession.superseded_reason == "legacy_deleted",
        ),
    ) == 1
    assert len((await _journal_v2(session, user.telegram_id, hide=False))["sessions"]) == 3  # замещённая не возвращается
    assert (await _journal_v2(session, user.telegram_id))["sessions"] == []
    body = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")).json()
    assert body["days"] == [{"date": "2026-10-02", "count": 3}]


async def test_unmigrated_user_sees_everything(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 982005)
    repo = WorkoutRepository(session)
    await repo.record_workout(**_kwargs(user, workout_set, BASE, 11))
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=1), 12))

    assert len(await _history(session, user.telegram_id)) == 2
    assert (await _journal_v2(session, user.telegram_id))["sessions"] == []


async def test_backfill_copy_is_hidden_regardless_of_timestamps_and_legacy_pair(session: AsyncSession):
    """Скрытие не сопоставляет по моменту/источнику с legacy-записью: копия с «уехавшим» performed_at
    и сессия без парной legacy-записи тоже скрыты (иначе удаление legacy воскресило бы копию)."""
    user, workout_set = await _legacy_user(session, 982006)
    workout = await WorkoutRepository(session).record_workout(**_kwargs(user, workout_set, BASE, 11))
    await _backfill(session, [workout])
    await session.execute(
        TrainingSession.__table__.update().where(TrainingSession.user_id == user.id)
        .values(performed_at=BASE + timedelta(microseconds=1), source=SessionSource.BACKDATED),
    )

    assert (await _journal_v2(session, user.telegram_id))["sessions"] == []
    assert [item["workout_id"] for item in await _history(session, user.telegram_id)] == [workout.id]


async def test_other_users_backfilled_session_is_not_shown_to_me(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 982007)
    other, other_set = await _legacy_user(session, 982008)
    mine = await WorkoutRepository(session).record_workout(**_kwargs(user, workout_set, BASE, 11))
    theirs = await WorkoutRepository(session).record_workout(**_kwargs(other, other_set, BASE, 11))
    await _backfill(session, [theirs])

    assert [item["workout_id"] for item in await _history(session, user.telegram_id)] == [mine.id]
    assert (await _journal_v2(session, user.telegram_id))["sessions"] == []
    assert (await _journal_v2(session, other.telegram_id))["sessions"] == []
    assert [item["workout_id"] for item in await _history(session, other.telegram_id)] == [theirs.id]


async def _live_flow_session(session: AsyncSession, user, *, exercise_id: int, **overrides) -> TrainingSession:
    """v2-сессия живого потока Mini App на тот же момент, что у legacy-записи."""
    repo = TrainingSessionRepository(session)
    created = await repo.create_session(
        user_id=user.id, source=SessionSource.PLAN, performed_at=BASE, effort=None, comment=None,
        blocks=[SessionBlockInput(exercise_id=exercise_id, sets=[
            SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(10), unit="reps"),
        ])],
    )
    for field, value in overrides.items():
        setattr(created, field, value)
    await session.flush()
    return created


async def test_live_flow_sessions_at_identical_timestamp_are_not_hidden(session: AsyncSession):
    """Сессия живого потока Mini App / Builder на тот же момент (другое упражнение / client_session_id /
    снимок / PlanItem / электив) — не backfill-копия: остаётся в Журнале v2. Каждый «почти-отпечаток»
    нарушает ровно одно условие."""
    user, workout_set = await _legacy_user(session, 982009)
    await WorkoutRepository(session).record_workout(**_kwargs(user, workout_set, BASE, 11))
    block_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    custom = Exercise(
        name="Свои подтягивания", metric_type=MetricType.REPS, category="pull_ups", subcategory="block_a",
        source_type="user", owner_user_id=user.id,
    )
    session.add(custom)
    await session.flush()

    expected: set[int] = set()
    # 1) другое (не backfill-овское) упражнение
    expected.add((await _live_flow_session(session, user, exercise_id=custom.id)).id)
    # 2) то же упражнение блока A, но с client_session_id (живой старт)
    expected.add((await _live_flow_session(session, user, exercise_id=block_a.id, client_session_id=uuid.uuid4())).id)
    # 3) со снимком Builder-тренировки
    expected.add((await _live_flow_session(session, user, exercise_id=block_a.id, workout_snapshot={"workout_id": 0, "title": "Builder", "items": []})).id)
    # 4) связанная с PlanItem (запуск из плана)
    linked = await _live_flow_session(session, user, exercise_id=block_a.id)
    plan = TrainingPlan(user_id=user.id)
    session.add(plan)
    await session.flush()
    plan_item = PlanItem(training_plan_id=plan.id, exercise_id=block_a.id, count_per_week=1)
    session.add(plan_item)
    await session.flush()
    session.add(SessionPlanItem(session_id=linked.id, plan_item_id=plan_item.id))
    expected.add(linked.id)
    # 5) запись «активность» (journal entry без упражнения блока A)
    expected.add((await _live_flow_session(session, user, exercise_id=block_a.id, activity_type="run")).id)
    # 6) электив (#279): та же таблица v2-сессий, source=elective
    elective = ElectiveWorkout(
        user_id=user.id, elective_type=ElectiveType.THREE_MINUTES, performed_at=BASE, reps_sequence=[4, 3, 2],
        total_reps=9, equipment_type=EquipmentType.BAND, equipment_value=Decimal("15.0"),
    )
    session.add(elective)
    await session.flush()
    elective_exercise = await _get_or_create_exercise(
        session, name="Факультатив: 3 минуты", subcategory="elective_three_minutes",
    )
    await _create_training_session_for_elective(session, elective, exercise_id=elective_exercise.id)
    await session.flush()
    expected.add(await session.scalar(
        select(TrainingSession.id).where(TrainingSession.user_id == user.id, TrainingSession.source == SessionSource.ELECTIVE),
    ))

    shown = {item["id"] for item in (await _journal_v2(session, user.telegram_id))["sessions"]}
    assert shown == expected
    # незавершённая сессия отпечатку не соответствует (и так не в Журнале): без фильтра status видна
    started = await _live_flow_session(session, user, exercise_id=block_a.id, status=SessionStatus.STARTED)
    shown_all = {item["id"] for item in (await _journal_v2(session, user.telegram_id, status=None))["sessions"]}
    assert shown_all == expected | {started.id}


async def test_backfilled_copies_do_not_distort_pagination(session: AsyncSession):
    """Срез offset/limit и has_more считаются ПОСЛЕ скрытия: три свежие backfill-копии не занимают место
    двух старых живых сессий."""
    user, workout_set = await _legacy_user(session, 982011)
    block_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    live_ids = []
    for hours in (0, 1):  # две живые (старые)
        created = await TrainingSessionRepository(session).create_session(
            user_id=user.id, source=SessionSource.PLAN, performed_at=BASE + timedelta(hours=hours), effort=None, comment=None,
            blocks=[SessionBlockInput(exercise_id=block_a.id, sets=[
                SetLogInput(set_number=1, metric_type=MetricType.REPS, value=Decimal(10), unit="reps"),
            ])],
        )
        created.client_session_id = uuid.uuid4()
        live_ids.append(created.id)
    repo = WorkoutRepository(session)
    workouts = [await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=h), 12)) for h in (2, 3, 4)]
    await _backfill(session, workouts)  # три свежие backfill-копии (новее живых)

    first = await _journal_v2(session, user.telegram_id, limit=1, offset=0)
    assert [item["id"] for item in first["sessions"]] == [live_ids[1]] and first["has_more"] is True
    second = await _journal_v2(session, user.telegram_id, limit=1, offset=1)
    assert [item["id"] for item in second["sessions"]] == [live_ids[0]] and second["has_more"] is False
    both = await _journal_v2(session, user.telegram_id, limit=2, offset=0)
    assert len(both["sessions"]) == 2 and both["has_more"] is False


async def test_journal_days_agree_with_the_list(session: AsyncSession):
    """Календарь = canonical_sessions; число сходится со списком Журнала (v2-список без карточек legacy +
    legacy-история) за месяц: каждая legacy-запись — одна копия, одна карточка, один счёт."""
    user, _workout_set, _post = await _migrated_user(session, 982010)
    block_a = await _get_or_create_exercise(session, name=_EXERCISE_BLOCK_A_NAME, subcategory="block_a")
    await _live_flow_session(session, user, exercise_id=block_a.id, client_session_id=uuid.uuid4())

    body = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")).json()
    # 4 копии legacy-записей (3 перенесённые + 1 после миграции, dual-write) + 1 живая v2-сессия
    assert body["days"] == [{"date": "2026-10-02", "count": 5}]
    listed = len((await _journal_v2(session, user.telegram_id))["sessions"]) + len(await _history(session, user.telegram_id))
    assert listed == 5
    assert body["latest_month"] == "2026-10"


async def test_latest_month_ignores_superseded_copies(session: AsyncSession):
    """latest_month не указывает на месяц, в котором осталась только замещённая копия удалённой legacy-записи."""
    user, workout_set = await _legacy_user(session, 982012)
    repo = WorkoutRepository(session)
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE, 11))
    december = await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(days=60), 12))

    body = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")).json()
    assert body["latest_month"] == "2026-12"
    deleted = await v2_delete(session, user.telegram_id, f"/api/history/{december.id}")
    assert deleted.status_code == 200, deleted.text
    body = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")).json()
    assert body["latest_month"] == "2026-10"
