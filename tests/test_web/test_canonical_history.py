"""#308 — Журнал, Профиль и Аналитика считают ОДНО множество: canonical_sessions (SESSION §6 A1–A8,
MIGRATION §4). Реальный Postgres, реальные писатели старой схемы (dual-write), реальный HTTP-слой.

Матрица: A целые счётчики · B Σ категорий == итог · C нет slug · D Журнал == Профиль == Аналитика ·
E «возрастной» профиль legacy + v2 · F правка legacy видна везде · G удаление legacy видно везде ·
H повторное сведение не дублирует · J неизвестная длительность · K правка даты · L правка значения ·
M клон считается один раз · N дубль копии и нативной сессии считается один раз · O внешняя активность."""

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workout
from app.db.models_program import Exercise, SessionBlock, SetLog, TrainingSession
from app.db.repositories.legacy_convergence import (
    REASON_NATIVE_DUPLICATE,
    ConvergenceOutcome,
    LegacyConvergenceRepository,
)
from app.db.repositories.workouts import WorkoutRepository
from app.domain.multi_program import MetricType
from app.domain.training_session_v2 import SessionOrigin
from app.services.legacy_history_convergence import LegacyHistoryConvergenceService
from tests.test_web._v2_client import v2_delete, v2_get, v2_patch, v2_post
from tests.test_web.test_journal_dedupe import (
    BASE,
    _edit_payload,
    _free_workout,
    _kwargs,
    _legacy_user,
)
from tests.test_web.test_profile import _get_profile

RAW_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
RAW_FRAGMENTS = ("pull_ups", "block_a", "block_b", "manual_custom", "elective_", "journal-log")
FULL_RANGE = "from=2026-01-01&to=2026-12-31"


# --- помощники -------------------------------------------------------------------------------------


async def _analytics(session: AsyncSession, user, query: str = FULL_RANGE) -> dict:
    response = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/analytics/training?{query}")
    assert response.status_code == 200, response.text
    return response.json()


async def _calendar_total(session: AsyncSession, user, months: tuple[str, ...] = ("2026-09", "2026-10")) -> int:
    total = 0
    for month in months:
        response = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/journal/days?month={month}")
        assert response.status_code == 200, response.text
        total += sum(day["count"] for day in response.json()["days"])
    return total


async def _journal_list_total(session: AsyncSession, user) -> int:
    """Журнал так, как его собирает экран: карточки legacy + v2-карточки без дублей legacy (exclude_legacy_cards)."""
    legacy = await v2_get(
        session, telegram_id=user.telegram_id, path="/api/history?date_from=2026-01-01&date_to=2026-12-31&limit=100",
    )
    assert legacy.status_code == 200, legacy.text
    v2 = await v2_get(
        session, telegram_id=user.telegram_id,
        path="/api/v2/sessions?status=completed&date_from=2026-01-01&date_to=2026-12-31&limit=200&exclude_legacy_cards=true",
    )
    assert v2.status_code == 200, v2.text
    return len(legacy.json()["items"]) + len(v2.json()["sessions"])


async def _all_totals(session: AsyncSession, user) -> dict[str, int]:
    analytics = await _analytics(session, user)
    return {
        "analytics_metrics": analytics["metrics"]["total_workouts"],
        "analytics_distribution": analytics["distribution"]["total_workouts"],
        "profile": (await _get_profile(session, telegram_id=user.telegram_id))["workouts_count"],
        "calendar": await _calendar_total(session, user),
        "journal_list": await _journal_list_total(session, user),
        "db": await session.scalar(
            select(func.count()).select_from(TrainingSession).where(
                TrainingSession.user_id == user.id, TrainingSession.status == "completed",
                TrainingSession.superseded_at.is_(None),
            ),
        ),
    }


def _assert_one_number(totals: dict[str, int], expected: int) -> None:
    assert totals == dict.fromkeys(totals, expected), totals


async def _pull_ups(session: AsyncSession) -> Exercise:
    exercise = Exercise(name="Подтягивания", metric_type=MetricType.REPS, category="pull_ups")
    session.add(exercise)
    await session.flush()
    return exercise


async def _post_backdated(
    session: AsyncSession, user, exercise: Exercise, at: datetime, reps: list[int], *, duration: int | None = None,
) -> dict:
    payload = {
        "source": "backdated", "performed_at": at.isoformat(),
        "blocks": [{
            "exercise_id": exercise.id,
            "sets": [{"set_number": i, "metric_type": "reps", "value": str(r), "unit": "reps"} for i, r in enumerate(reps, 1)],
        }],
    }
    if duration is not None:
        payload["duration_seconds"] = duration
    response = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def _post_activity(session: AsyncSession, user, at: datetime, minutes: int, kind: str = "running") -> dict:
    response = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/sessions", payload={
        "source": "freeform", "performed_at": at.isoformat(), "blocks": [], "activity_type": kind,
        "duration_seconds": minutes * 60,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in _strings(value)]
    return []


async def _mixed_history(session: AsyncSession, telegram_id: int):
    """Каскадная + бэкдейт + свободные подтягивания (legacy, dual-write), электив, а также нативные записи v2:
    ручная тренировка, внешняя активность и клон ручной."""
    user, workout_set = await _legacy_user(session, telegram_id)
    exercise = await _pull_ups(session)  # каталог «Подтягивания» есть до первой записи (как в проде, сид b7d2e9f4a1c3)
    repo = WorkoutRepository(session)
    await repo.record_workout(**_kwargs(user, workout_set, BASE, 11))
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=1), 12))
    await _free_workout(session, user, workout_set, BASE + timedelta(hours=2), 13)
    manual = await _post_backdated(session, user, exercise, BASE + timedelta(days=1), [8, 8], duration=1500)
    await _post_activity(session, user, BASE + timedelta(days=2), 45)
    clone = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{manual['id']}/clone", {})
    assert clone.status_code == 201, clone.text
    return user, workout_set, manual, clone.json()


# --- A, B, C, D ------------------------------------------------------------------------------------


async def test_journal_profile_and_analytics_report_the_same_integer_total(session: AsyncSession):
    user, _workout_set, _manual, _clone = await _mixed_history(session, 990001)

    totals = await _all_totals(session, user)
    _assert_one_number(totals, 6)  # 3 legacy + ручная + активность + клон ручной (клон — обычная тренировка)

    analytics = await _analytics(session, user)
    distribution = analytics["distribution"]
    assert isinstance(analytics["metrics"]["total_workouts"], int)
    assert all(isinstance(c["workouts"], int) for c in distribution["categories"])
    assert all(isinstance(s["workouts"], int) for c in distribution["categories"] for s in c["subcategories"])
    assert all(isinstance(w["workouts"], int) for w in analytics["metrics"]["weeks"])
    # B: категории складываются ровно в итог, одна категория на тренировку
    assert sum(c["workouts"] for c in distribution["categories"]) == distribution["total_workouts"] == 6
    by_name = {c["name"]: c["workouts"] for c in distribution["categories"]}
    assert by_name["Подтягивания"] == 5 and by_name["Другая активность"] == 1


async def test_no_internal_slug_is_visible_in_analytics_or_journal(session: AsyncSession):
    user, _workout_set, _manual, _clone = await _mixed_history(session, 990002)
    analytics = await _analytics(session, user)
    journal = await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed&limit=100")
    assert journal.status_code == 200

    visible = _strings({
        "categories": analytics["distribution"],
        "exercises": [{"name": e["exercise_name"]} for e in analytics["exercises"]],
        "titles": [
            {"title": s.get("title"), "blocks": [b.get("exercise_name") for b in s["blocks"]]}
            for s in journal.json()["sessions"]
        ],
    })
    assert visible, "нечего проверять"
    assert not [s for s in visible if RAW_KEY.match(s) or any(f in s for f in RAW_FRAGMENTS)], visible


# --- E, H: возрастной профиль и повторное сведение ----------------------------------------------------


async def _age_the_history(session: AsyncSession, user) -> dict:
    """Превратить историю пользователя в то, что лежит на проде ДО #308: копии backfill-а без ключа legacy_id;
    записи, добавленные старым кодом после backfill, без копий; запись, удалённая в legacy (копия-сирота);
    запись, отредактированная в legacy после backfill (копия устарела); одна запись нетронута."""
    workouts = (await session.execute(select(Workout).where(Workout.user_id == user.id).order_by(Workout.id))).scalars().all()
    first, second, third, fourth, fifth = (w.id for w in workouts[:5])
    unsynced_at = [w.performed_at for w in workouts[2:5] if w.id in (third, fifth)]
    await session.execute(text("UPDATE training_sessions SET legacy_id = NULL WHERE user_id = :u AND origin = 'legacy_backfill'"), {"u": user.id})
    for moment in unsynced_at:  # «старый код» записал после backfill — копии нет
        await session.execute(text("DELETE FROM training_sessions WHERE user_id = :u AND performed_at = :t AND origin = 'legacy_backfill'"), {"u": user.id, "t": moment})
    # second: удалена в legacy мимо dual-write (старым кодом) — копия осталась
    await session.execute(text("DELETE FROM workouts WHERE id = :id"), {"id": second})
    # first: отредактирована в legacy старым кодом — копия хранит прежние повторения
    await session.execute(text("UPDATE blocks SET max_reps = 21 WHERE workout_id = :id AND block_type = 'a'"), {"id": first})
    session.expire_all()
    await session.refresh(user)
    return {"edited": first, "deleted": second, "unsynced": [third, fifth], "untouched": fourth}


async def test_aged_profile_with_legacy_and_v2_history_reconciles_after_convergence(session: AsyncSession):
    user, workout_set, _manual, _clone = await _mixed_history(session, 990003)
    repo = WorkoutRepository(session)
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=3), 14))
    await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=4), 15))
    ids = await _age_the_history(session, user)

    # до сведения (как на проде сразу после выкладки): виды считают по-разному — именно это и чинится
    before = await _all_totals(session, user)
    assert len(set(before.values())) > 1, before
    service = LegacyHistoryConvergenceService(session)

    dry = await service.converge_user(user.id, apply=False)
    assert dry.counts["bound"] == 1 and dry.counts["created"] == 3 and dry.counts["superseded"] == 2
    assert await session.scalar(select(func.count()).select_from(TrainingSession).where(
        TrainingSession.user_id == user.id, TrainingSession.legacy_id.is_not(None),
    )) == 0, "dry-run ничего не пишет"

    applied = await service.converge_user(user.id, apply=True)
    assert applied.mutations == dry.mutations > 0
    await session.flush()

    # 4 живые legacy-записи (вторая удалена) + ручная + активность + клон = 7; сирота и устаревшая копия замещены
    _assert_one_number(await _all_totals(session, user), 7)
    superseded = (await session.execute(
        select(TrainingSession.superseded_reason).where(TrainingSession.user_id == user.id, TrainingSession.superseded_at.is_not(None)),
    )).scalars().all()
    assert sorted(superseded) == ["legacy_replaced", "legacy_replaced"]
    # правка legacy до выкладки dual-write теперь видна и в копии
    edited_copy = await session.scalar(select(TrainingSession).where(
        TrainingSession.origin == "legacy_backfill", TrainingSession.legacy_id == ids["edited"], TrainingSession.superseded_at.is_(None),
    ))
    assert edited_copy is not None
    values = (await session.execute(
        select(SetLog.value).join(SessionBlock, SessionBlock.id == SetLog.session_block_id)
        .where(SessionBlock.session_id == edited_copy.id, SessionBlock.order_index == 0, SetLog.is_max_set.is_(True)),
    )).scalars().all()
    assert values == [Decimal(21)]

    # H: повторный apply = 0 изменений, копий не прибавилось
    count = select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id)
    rows_before = await session.scalar(count)
    again = await service.converge_user(user.id, apply=True)
    assert again.mutations == 0, again.counts
    assert await session.scalar(count) == rows_before
    _assert_one_number(await _all_totals(session, user), 7)


async def test_repeated_convergence_and_dual_write_never_duplicate_a_copy(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 990004)
    workout = await WorkoutRepository(session).record_backdated_workout(**_kwargs(user, workout_set, BASE, 11))
    repo = LegacyConvergenceRepository(session)

    for _ in range(3):  # backfill-скрипт и dual-write делят одну функцию — повтор ничего не меняет
        assert await repo.sync_workout(workout) is ConvergenceOutcome.UNCHANGED
    copies = (await session.execute(
        select(TrainingSession).where(TrainingSession.origin == "legacy_backfill", TrainingSession.legacy_id == workout.id),
    )).scalars().all()
    assert len(copies) == 1 and copies[0].revision == 0

    # на уровне БД ключ (origin, legacy_id) уникален: даже обход кода не создаст вторую копию
    duplicate = TrainingSession(
        user_id=user.id, source=copies[0].source, status=copies[0].status, performed_at=BASE,
        origin=SessionOrigin.LEGACY_BACKFILL.value, legacy_id=workout.id,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.flush()


# --- F, G: правка и удаление legacy ---------------------------------------------------------------------


async def test_legacy_edit_is_reflected_in_every_view(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 990005)
    await _pull_ups(session)
    repo = WorkoutRepository(session)
    await repo.record_workout(**_kwargs(user, workout_set, BASE, 11))
    target = await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=1), 12))

    before = await _analytics(session, user)
    exercise = next(e for e in before["exercises"] if e["exercise_name"] == "Подтягивания")
    best_before = max(Decimal(p["best"]) for panel in exercise["panels"] if panel["protocol_type"] == "max_effort" for p in panel["points"])
    assert best_before == 12

    edited = await v2_patch(session, user.telegram_id, f"/api/history/{target.id}", _edit_payload(max_a=17))
    assert edited.status_code == 200, edited.text

    after = await _analytics(session, user)
    exercise = next(e for e in after["exercises"] if e["exercise_name"] == "Подтягивания")
    max_panel = next(p for p in exercise["panels"] if p["protocol_type"] == "max_effort")
    assert Decimal(max_panel["best"]) == 17 and max_panel["session_count"] == 2
    _assert_one_number(await _all_totals(session, user), 2)  # правка не дублирует и не теряет тренировку


async def test_legacy_delete_is_reflected_in_every_view(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 990006)
    await _pull_ups(session)
    repo = WorkoutRepository(session)
    await repo.record_workout(**_kwargs(user, workout_set, BASE, 11))
    doomed = await repo.record_backdated_workout(**_kwargs(user, workout_set, BASE + timedelta(hours=1), 12))
    _assert_one_number(await _all_totals(session, user), 2)

    deleted = await v2_delete(session, user.telegram_id, f"/api/history/{doomed.id}")
    assert deleted.status_code == 200, deleted.text

    _assert_one_number(await _all_totals(session, user), 1)
    analytics = await _analytics(session, user)
    exercise = next(e for e in analytics["exercises"] if e["exercise_name"] == "Подтягивания")
    assert next(p for p in exercise["panels"] if p["protocol_type"] == "max_effort")["session_count"] == 1
    # строка копии остаётся (архивировать, не удалять), но замещена
    assert await session.scalar(select(func.count()).select_from(TrainingSession).where(
        TrainingSession.user_id == user.id, TrainingSession.superseded_reason == "legacy_deleted",
    )) == 1


# --- J, K, L: длительность, правка даты и значения (J10) -------------------------------------------------


async def test_unknown_duration_counts_the_workout_but_not_minutes(session: AsyncSession):
    user, *_ = await _mixed_history(session, 990007)
    metrics = (await _analytics(session, user))["metrics"]
    # legacy-копии и клон не имеют длительности (unknown, не 0); ручная — 25 мин, активность — 45
    assert metrics["total_workouts"] == 6 and metrics["without_duration"] == 4
    assert metrics["total_minutes"] == 70
    assert sum(w["minutes"] for w in metrics["weeks"]) == 70


async def test_date_and_value_edit_move_series_journal_day_and_exercise_history(session: AsyncSession):
    user = (await _legacy_user(session, 990008))[0]
    exercise = await _pull_ups(session)
    session_json = await _post_backdated(session, user, exercise, datetime(2026, 10, 7, 9, 0, tzinfo=UTC), [8, 8], duration=1800)
    await _post_backdated(session, user, exercise, datetime(2026, 10, 8, 9, 0, tzinfo=UTC), [6, 6], duration=600)

    async def snapshot() -> dict:
        analytics = await _analytics(session, user, "from=2026-09-21&to=2026-10-11")
        weeks = {w["week_start"]: (w["workouts"], w["minutes"]) for w in analytics["metrics"]["weeks"]}
        days = {d["date"]: d["count"] for d in (await v2_get(session, user.telegram_id, "/api/v2/journal/days?month=2026-09")).json()["days"]}
        days.update({d["date"]: d["count"] for d in (await v2_get(session, user.telegram_id, "/api/v2/journal/days?month=2026-10")).json()["days"]})
        reps = next(e for e in analytics["exercises"] if e["exercise_name"] == "Подтягивания")
        panel = next(p for p in reps["panels"] if p["protocol_type"] == "reps_sets")
        return {"weeks": weeks, "days": days, "panel": panel, "total": analytics["metrics"]["total_workouts"]}

    before = await snapshot()
    assert before["weeks"] == {"2026-09-21": (0, 0), "2026-09-28": (0, 0), "2026-10-05": (2, 40)}
    assert before["days"] == {"2026-10-07": 1, "2026-10-08": 1}
    assert Decimal(before["panel"]["total_reps"]) == 28 and before["total"] == 2

    edited = await v2_patch(session, user.telegram_id, f"/api/v2/sessions/{session_json['id']}", {
        "performed_on": "2026-09-24", "sets": [{"block_index": 0, "set_number": 1, "value": "20"}],
    })
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["duration_seconds"] == 1800  # R4: дата не стирает длительность

    after = await snapshot()
    assert after["weeks"] == {"2026-09-21": (1, 30), "2026-09-28": (0, 0), "2026-10-05": (1, 10)}  # тренировка и её минуты уехали
    assert after["days"] == {"2026-09-24": 1, "2026-10-08": 1}
    assert Decimal(after["panel"]["total_reps"]) == 20 + 8 + 12 and Decimal(after["panel"]["best_set"]) == 20
    assert after["total"] == 2  # итог не изменился
    point_days = [p["at"][:10] for p in after["panel"]["points"]]
    assert point_days == ["2026-09-24", "2026-10-08"]  # история упражнения упорядочена по НОВОЙ дате
    # Журнал: карточка на новом дне, старого дня нет
    listed = await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed&date_from=2026-09-24&date_to=2026-09-24")
    assert [s["id"] for s in listed.json()["sessions"]] == [session_json["id"]]


# --- M, N, O ------------------------------------------------------------------------------------------


async def test_clone_counts_as_one_more_global_workout_and_carries_no_plan_credit(session: AsyncSession):
    user = (await _legacy_user(session, 990009))[0]
    exercise = await _pull_ups(session)
    original = await _post_backdated(session, user, exercise, BASE, [8, 8], duration=900)
    before = (await _analytics(session, user))["metrics"]["total_workouts"]
    cloned = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{original['id']}/clone", {})
    assert cloned.status_code == 201, cloned.text

    totals = await _all_totals(session, user)
    _assert_one_number(totals, before + 1)  # ровно +1, не +2 и не 0
    clone_row = await session.get(TrainingSession, cloned.json()["id"])
    assert clone_row.plan_item_id is None and clone_row.program_inclusion_id is None
    assert clone_row.superseded_at is None and clone_row.origin == "native"


async def test_legacy_copy_that_duplicates_a_native_session_counts_once(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 990010)
    legacy = await WorkoutRepository(session).record_backdated_workout(**_kwargs(user, workout_set, BASE, 11))
    exercise = await _pull_ups(session)
    native = await _post_backdated(session, user, exercise, BASE, [10, 10, 10, 11])
    _assert_one_number(await _all_totals(session, user), 2)  # до замещения — две строки

    repo = LegacyConvergenceRepository(session)
    copy = await repo.find_copy(SessionOrigin.LEGACY_BACKFILL, legacy.id)
    assert await repo.supersede_copy(copy, reason=REASON_NATIVE_DUPLICATE, superseded_by_id=native["id"])
    assert not await repo.supersede_copy(copy, reason=REASON_NATIVE_DUPLICATE)  # идемпотентно
    _assert_one_number(await _all_totals(session, user), 1)

    # повторное сведение/правка legacy замещение не снимает (иначе дубль вернулся бы)
    assert await repo.sync_workout(legacy) is ConvergenceOutcome.UNCHANGED
    await LegacyHistoryConvergenceService(session).converge_user(user.id, apply=True)
    _assert_one_number(await _all_totals(session, user), 1)
    await session.refresh(copy)
    assert copy.superseded_by_id == native["id"] and copy.superseded_reason == REASON_NATIVE_DUPLICATE


async def test_external_activity_has_a_deterministic_category_and_display_name(session: AsyncSession):
    user = (await _legacy_user(session, 990011))[0]
    created = await _post_activity(session, user, BASE, 45, "running")
    assert created["title"] == "Бег"
    analytics = await _analytics(session, user)
    other = next(c for c in analytics["distribution"]["categories"] if c["name"] == "Другая активность")
    assert (other["workouts"], other["minutes"]) == (1, 45)
    assert [(s["name"], s["workouts"], s["minutes"]) for s in other["subcategories"]] == [("Бег", 1, 45)]
    assert analytics["exercises"] == []  # A8: внешняя активность не попадает в историю упражнений
    _assert_one_number(await _all_totals(session, user), 1)


# --- A4: одна история упражнения для любых источников -----------------------------------------------------


async def test_exercise_history_is_one_identity_across_legacy_manual_and_clone(session: AsyncSession):
    user, workout_set = await _legacy_user(session, 990012)
    public = await _pull_ups(session)
    # служебные упражнения курса, созданные при первой записи, указывают на публичное «Подтягивания» (E2)
    await WorkoutRepository(session).record_backdated_workout(**_kwargs(user, workout_set, BASE, 11))  # legacy -> блоки A/Б курса
    manual = await _post_backdated(session, user, public, BASE + timedelta(days=1), [9, 9, 9])
    cloned = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{manual['id']}/clone", {})
    assert cloned.status_code == 201

    analytics = await _analytics(session, user)
    assert [e["exercise_name"] for e in analytics["exercises"]] == ["Подтягивания"]  # одна идентичность, не три
    assert analytics["exercises"][0]["exercise_id"] == public.id
    reps = next(p for p in analytics["exercises"][0]["panels"] if p["protocol_type"] == "reps_sets")
    assert reps["session_count"] == 3  # legacy-копия (A+Б), ручная, клон
    maxes = next(p for p in analytics["exercises"][0]["panels"] if p["protocol_type"] == "max_effort")
    assert maxes["session_count"] == 1 and Decimal(maxes["best"]) == 11  # подход на максимум — отдельная панель
    assert json.dumps(analytics, ensure_ascii=False).count("Подтягивания —") == 0  # служебные имена не всплывают


# --- J1 / J9 (аналитическая часть): курс, ручная запись, клон и активность — одна согласованная история -------


async def test_course_session_manual_log_clone_and_activity_stay_consistent(session: AsyncSession, user):
    import uuid

    from app.db.models_program import PlanItem
    from app.db.repositories.training_plans import TrainingPlanRepository
    from tests.test_web.test_v2_live_session import (
        _create_inclusion,
        _exercise_ids_by_role,
        _make_step_program,
    )

    user.timezone = "UTC"
    program = await _make_step_program(session, category="pull_ups")  # курс «Подтягивания»: блоки A/Б
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    roles = _exercise_ids_by_role(inclusion)
    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    item_ids = {}
    for role, exercise_id in roles.items():
        item = PlanItem(training_plan_id=plan.id, exercise_id=exercise_id, count_per_week=3, program_inclusion_id=inclusion["id"])
        session.add(item)
        await session.flush()
        item_ids[role] = item.id

    # J1: живая сессия курса, 25 минут активного времени
    started = await v2_post(session, user.telegram_id, "/api/v2/sessions/live", {
        "client_session_id": str(uuid.uuid4()), "plan_item_ids": [item_ids["block_a"], item_ids["block_b"]],
    })
    assert started.status_code == 200, started.text
    live_id = started.json()["id"]
    await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{live_id}/sets:batch", {"sets": [
        {"set_index": i, "exercise_id": roles["block_a" if i < 3 else "block_b"], "value": str(v)}
        for i, v in enumerate([11, 11, 11, 4, 4, 4, 4])
    ]})
    done = await v2_post(
        session, user.telegram_id, f"/api/v2/sessions/live/{live_id}/complete", {"abandoned": False, "active_elapsed_ms": 1_500_000},
    )
    assert done.status_code == 200, done.text

    analytics = await _analytics(session, user, FULL_RANGE)
    assert analytics["metrics"]["total_workouts"] == 1 and analytics["metrics"]["total_minutes"] == 25
    categories = {c["name"]: c for c in analytics["distribution"]["categories"] if c["workouts"]}
    assert list(categories) == ["Подтягивания"] and categories["Подтягивания"]["workouts"] == 1
    assert categories["Подтягивания"]["minutes"] == 25

    # ручная запись и клон курсовой сессии (клон — обычная тренировка, не старт курса)
    cloned = await v2_post(session, user.telegram_id, f"/api/v2/sessions/{live_id}/clone", {})
    assert cloned.status_code == 201, cloned.text
    manual = await _post_backdated(session, user, await _pull_ups(session), datetime.now(UTC) - timedelta(days=3), [7, 7], duration=900)
    activity = await _post_activity(session, user, datetime.now(UTC) - timedelta(days=2), 45)  # J9

    analytics = await _analytics(session, user, FULL_RANGE)
    assert analytics["metrics"]["total_workouts"] == 4
    categories = {c["name"]: c for c in analytics["distribution"]["categories"] if c["workouts"]}
    assert {n: (c["workouts"], c["minutes"]) for n, c in categories.items()} == {
        "Подтягивания": (3, 40), "Другая активность": (1, 45),  # клон: 0 мин (не измерялся), ручная 15 мин
    }
    assert analytics["metrics"]["total_minutes"] == 85 == sum(w["minutes"] for w in analytics["metrics"]["weeks"])
    totals = await _all_totals(session, user)
    assert len(set(totals.values())) == 1 and totals["profile"] == 4
    assert manual["id"] and activity["id"]
