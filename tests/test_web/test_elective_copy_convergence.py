"""Сведение (#308) не дублирует и не воскрешает копии факультативов, которые старый backfill (#163) уже создал,
а пользователь потом отредактировал или удалил в Журнале v2 (STAGING_RC_REHEARSAL §8).

Копии создаются так, как их писал старый backfill (без ключа legacy_id, одной транзакцией с TrainingPlan);
правка и удаление — тем, что делало со строками старое API (#262/#279): PATCH меняет значение подхода (note с
упакованным форматом сохраняется) или performed_at, DELETE удаляет дерево сессии. Хронология created_at задаётся
явно: тест идёт в одной транзакции, где now() у всех строк одинаков.

Штатные хронологии (created_at факультатива / копий / плана; копии и план старого backfill — одна транзакция, это
показано запуском самого старого backfill: docs/rehearsal/old_backfill_created_at.py, STAGING_RC_REHEARSAL §8):
* ``pre_plan`` — прод: факультативы записаны задолго до миграции;
* ``same_txn`` — фикстура репетиции (пользователь B): всё в одной транзакции.
Нештатная история (копия вне транзакции плана, копия без плана — ручной SQL/сиды) — отдельные тесты guard'а."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ElectiveWorkout
from app.db.models_program import SessionBlock, SetLog, TrainingPlan, TrainingSession
from app.db.repositories.legacy_convergence import LegacyConvergenceRepository, elective_note
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.multi_program import MetricType, SessionSource
from app.domain.training_session_v2 import SessionOrigin
from app.services.legacy_history_convergence import LegacyHistoryConvergenceService
from scripts.backfill_multi_program import _render_unresolved, converge_history_all
from tests.test_web.test_canonical_history import _all_totals, _assert_one_number
from tests.test_web.test_journal_dedupe import BASE, _free_workout, _legacy_user

BACKFILL_AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CHRONOLOGIES = {
    # (created_at факультатива, created_at плана); копии старого backfill — всегда BACKFILL_AT
    "pre_plan": (BACKFILL_AT - timedelta(days=30), BACKFILL_AT),
    "same_txn": (BACKFILL_AT, BACKFILL_AT),
}


# --- «старый код» --------------------------------------------------------------------------------------


async def _old_elective(
    session: AsyncSession, user, kind: ElectiveType, at: datetime, total: int, sequence: list[int] | None,
    created_at: datetime,
) -> ElectiveWorkout:
    """Факультатив, записанный старым кодом: без dual-write (ElectiveWorkoutRepository.create уже пишет копию)."""
    elective = ElectiveWorkout(
        user_id=user.id, elective_type=kind, performed_at=at, total_reps=total, reps_sequence=sequence,
        equipment_type=EquipmentType.BODYWEIGHT, equipment_value=None,
    )
    session.add(elective)
    await session.flush()
    await session.execute(text("UPDATE elective_workouts SET created_at = :c WHERE id = :i"), {"c": created_at, "i": elective.id})
    await session.refresh(elective)
    return elective


async def _old_backfill_copy(
    session: AsyncSession, elective: ElectiveWorkout, *, created_at: datetime = BACKFILL_AT, origin: str | None = "legacy_elective",
) -> TrainingSession:
    """scripts/backfill_multi_program.py::_create_training_session_for_elective кода develop/current (1735cad):
    без legacy_id; origin проставляет миграция f4c1a7e9b3d2 (None — копия, записанная старым кодом уже на новой
    схеме, до классификации)."""
    exercise_id = await LegacyConvergenceRepository(session).elective_exercise_id(elective.elective_type)
    copy = TrainingSession(
        user_id=elective.user_id, source=SessionSource.ELECTIVE, status="completed", performed_at=elective.performed_at,
        origin=origin,
    )
    session.add(copy)
    await session.flush()
    block = SessionBlock(session_id=copy.id, order_index=0, exercise_id=exercise_id)
    session.add(block)
    await session.flush()
    session.add(SetLog(
        session_block_id=block.id, set_number=1, is_max_set=False, metric_type=MetricType.REPS,
        value=Decimal(elective.total_reps), unit="reps", note=elective_note(elective),
    ))
    await session.flush()
    await session.execute(text("UPDATE training_sessions SET created_at = :c WHERE id = :i"), {"c": created_at, "i": copy.id})
    return copy


async def _plan(session: AsyncSession, user, created_at: datetime) -> None:
    session.add(TrainingPlan(user_id=user.id))
    await session.flush()
    await session.execute(text("UPDATE training_plans SET created_at = :c WHERE user_id = :u"), {"c": created_at, "u": user.id})


async def _old_edit_value(session: AsyncSession, copy: TrainingSession, value: int) -> None:
    """Старое PATCH /api/v2/sessions/{id} (sets): значение подхода; note факультатива сохраняется (#279)."""
    await session.execute(text(
        "UPDATE set_logs SET value = :v WHERE session_block_id IN (SELECT id FROM session_blocks WHERE session_id = :s)",
    ), {"v": value, "s": copy.id})


async def _old_move_date(session: AsyncSession, copy: TrainingSession, days: int) -> None:
    """Старое PATCH /api/v2/sessions/{id} (performed_on): другой день, то же время суток."""
    await session.execute(text("UPDATE training_sessions SET performed_at = performed_at + make_interval(days => :d) WHERE id = :s"),
                          {"d": days, "s": copy.id})


async def _old_delete(session: AsyncSession, copy: TrainingSession) -> None:
    """Старое DELETE /api/v2/sessions/{id}: TrainingSessionRepository.delete_session — дерево удаляется."""
    await session.execute(text("DELETE FROM training_sessions WHERE id = :s"), {"s": copy.id})


# --- помощники -------------------------------------------------------------------------------------------


async def _reload(session: AsyncSession, *objects) -> None:
    """Сырые UPDATE/DELETE «старого кода» мимо ORM: сбросить identity map и перечитать нужные объекты."""
    session.expire_all()
    for obj in objects:
        await session.refresh(obj)


async def _elective_rows(session: AsyncSession, user) -> list[tuple]:
    """(id, origin, legacy_id, performed_at, значения, superseded, revision) всех копий факультативов."""
    rows = (await session.execute(
        select(TrainingSession).where(TrainingSession.user_id == user.id, TrainingSession.source == SessionSource.ELECTIVE)
        .order_by(TrainingSession.id).execution_options(populate_existing=True),
    )).scalars().all()
    result = []
    for row in rows:
        values = (await session.execute(
            select(SetLog.value).join(SessionBlock, SessionBlock.id == SetLog.session_block_id)
            .where(SessionBlock.session_id == row.id).order_by(SetLog.set_number),
        )).scalars().all()
        result.append((row.id, row.origin, row.legacy_id, row.performed_at, tuple(values), row.superseded_at is not None, row.revision))
    return result


async def _scenario(session: AsyncSession, telegram_id: int, chronology: str):
    """Пользователь «после старого backfill»: 4 факультатива, у каждого копия старого backfill; затем через
    старое API: E1 — значение 15→20, E2 — перенос на день раньше, E3 — не тронут, E4 — копия удалена."""
    elective_created, plan_created = CHRONOLOGIES[chronology]
    user, _ = await _legacy_user(session, telegram_id)
    await _plan(session, user, plan_created)
    specs = (
        (ElectiveType.MAX_REPS_LADDER, 15, [5, 4, 3, 3]),
        (ElectiveType.THREE_MINUTES, 9, [9]),
        (ElectiveType.W_LADDER, 18, [6, 6, 6]),
        (ElectiveType.VOLUME_TARGET, 30, None),
    )
    electives, copies = [], []
    for index, (kind, total, sequence) in enumerate(specs):
        elective = await _old_elective(session, user, kind, BASE + timedelta(hours=index), total, sequence, elective_created)
        electives.append(elective)
        copies.append(await _old_backfill_copy(session, elective))
    await _old_edit_value(session, copies[0], 20)
    await _old_move_date(session, copies[1], -1)
    await _old_delete(session, copies[3])
    await _reload(session, user, *electives, *copies[:3])
    return user, electives, copies


async def _converge(session: AsyncSession, user, *, apply: bool):
    report = await LegacyHistoryConvergenceService(session).converge_user(user.id, apply=apply)
    await session.flush()
    return report


# --- untouched / edited value / moved date / deleted copy; до и после плана --------------------------------


@pytest.mark.parametrize("chronology", list(CHRONOLOGIES))
async def test_edited_and_deleted_backfilled_copies_are_neither_duplicated_nor_resurrected(session: AsyncSession, chronology):
    user, (e1, e2, e3, e4), (c1, c2, c3, _c4) = await _scenario(session, 991001, chronology)
    e2_moved_to = c2.performed_at
    before_rows = await _elective_rows(session, user)
    before_totals = await _all_totals(session, user)
    _assert_one_number(before_totals, 3)  # E1, E2 (правленые), E3; E4 удалён

    dry = await _converge(session, user, apply=False)
    assert await _elective_rows(session, user) == before_rows, "dry-run ничего не пишет"
    assert dry.counts["bound"] == 1 and dry.counts["elective_created"] == 0, dry.counts
    assert dry.counts["ambiguous_elective_without_copy"] == 3, dry.counts

    applied = await _converge(session, user, apply=True)
    assert applied.counts == dry.counts and applied.mutations == dry.mutations == 1
    assert sorted(applied.ambiguous, key=lambda a: a["elective_id"]) == sorted(dry.ambiguous, key=lambda a: a["elective_id"])
    by_elective = {item["elective_id"]: item for item in applied.ambiguous}
    assert set(by_elective) == {e1.id, e2.id, e4.id}
    assert {item["reason"] for item in applied.ambiguous} == {"backfilled_copy_edited_or_deleted"}
    # кандидаты — только для оператора: копии того же формата, не моложе факультатива; ничего не привязано
    assert by_elective[e1.id]["candidate_copy_ids"] == [c1.id]
    assert by_elective[e2.id]["candidate_copy_ids"] == [c2.id]
    assert by_elective[e4.id]["candidate_copy_ids"] == []

    after = {row[0]: row for row in await _elective_rows(session, user)}
    assert set(after) == {c1.id, c2.id, c3.id}, "ни одной новой копии: ни дубля правленых, ни воскрешения E4"
    assert after[c3.id][1:3] == ("legacy_elective", e3.id)  # нетронутая — привязана
    assert after[c1.id][2] is None and after[c1.id][4] == (Decimal(20),)  # правка значения сохранена, без ключа
    assert after[c2.id][2] is None and after[c2.id][3] == e2_moved_to == e2.performed_at - timedelta(days=1)  # перенос сохранён
    assert all(row[6] == 0 and not row[5] for row in after.values()), "содержимое и замещение не тронуты"
    _assert_one_number(await _all_totals(session, user), 3)

    again = await _converge(session, user, apply=True)
    assert again.mutations == 0 and again.counts["elective_created"] == 0, again.counts
    assert again.counts["ambiguous_elective_without_copy"] == 3
    assert {row[0]: row for row in await _elective_rows(session, user)} == after
    _assert_one_number(await _all_totals(session, user), 3)


@pytest.mark.parametrize("chronology", list(CHRONOLOGIES))
async def test_elective_recorded_after_the_old_backfill_still_gets_its_copy(session: AsyncSession, chronology):
    """Записан старым кодом ПОСЛЕ прогона backfill (копий при записи старый код не создавал) — копия создаётся,
    даже рядом с правленой/удалённой копией; второй прогон её не дублирует."""
    user, _electives, _copies = await _scenario(session, 991002, chronology)
    late = await _old_elective(
        session, user, ElectiveType.THREE_MINUTES, BASE + timedelta(days=5), 11, [11], BACKFILL_AT + timedelta(days=5),
    )
    applied = await _converge(session, user, apply=True)
    assert applied.counts["elective_created"] == 1 and applied.counts["ambiguous_elective_without_copy"] == 3
    assert late.id not in {item["elective_id"] for item in applied.ambiguous}
    assert await session.scalar(select(func.count()).select_from(TrainingSession).where(
        TrainingSession.origin == SessionOrigin.LEGACY_ELECTIVE.value, TrainingSession.legacy_id == late.id,
    )) == 1
    _assert_one_number(await _all_totals(session, user), 4)
    again = await _converge(session, user, apply=True)
    assert again.mutations == 0
    _assert_one_number(await _all_totals(session, user), 4)


async def test_dual_write_copy_of_a_new_elective_does_not_mark_an_older_uncopied_one_as_processed(session: AsyncSession):
    """Окно отката: старый код записал факультатив без копии (после плана — backfill его не переносил), потом
    новый код записал следующий (копия dual-write в той же транзакции). Копия dual-write — не след нештатной
    истории и не прогон backfill: более ранний факультатив получает копию (первый импорт)."""
    user, _ = await _legacy_user(session, 991003)
    await _plan(session, user, BACKFILL_AT - timedelta(days=60))
    orphan = await _old_elective(session, user, ElectiveType.W_LADDER, BASE, 12, [4, 4, 4], BACKFILL_AT)
    newer = await _old_elective(
        session, user, ElectiveType.THREE_MINUTES, BASE + timedelta(hours=2), 9, [9], BACKFILL_AT + timedelta(hours=1),
    )
    await LegacyConvergenceRepository(session).sync_elective(newer)  # dual-write: ключ сразу
    await session.execute(text("UPDATE training_sessions SET created_at = :c WHERE legacy_id = :i AND origin = 'legacy_elective'"),
                          {"c": newer.created_at, "i": newer.id})
    applied = await _converge(session, user, apply=True)
    assert applied.counts["elective_created"] == 1 and not applied.ambiguous, applied.counts
    assert await session.scalar(select(func.count()).select_from(TrainingSession).where(
        TrainingSession.legacy_id == orphan.id, TrainingSession.origin == SessionOrigin.LEGACY_ELECTIVE.value,
    )) == 1


async def test_deleted_copy_stays_deleted_after_the_untouched_ones_get_their_key(session: AsyncSession):
    """После первого apply неключевых копий не остаётся (нетронутая получила ключ), но удалённая копия на втором
    прогоне не воскресает: решение не зависит от того, что сведение само меняет."""
    user, _ = await _legacy_user(session, 991004)
    await _plan(session, user, BACKFILL_AT)
    kept = await _old_elective(session, user, ElectiveType.W_LADDER, BASE, 12, [4, 4, 4], BACKFILL_AT - timedelta(days=3))
    gone = await _old_elective(
        session, user, ElectiveType.VOLUME_TARGET, BASE + timedelta(hours=1), 40, None, BACKFILL_AT - timedelta(days=3),
    )
    await _old_backfill_copy(session, kept)
    await _old_delete(session, await _old_backfill_copy(session, gone))
    await _reload(session, user, kept, gone)

    first = await _converge(session, user, apply=True)
    assert (first.counts["bound"], first.counts["elective_created"]) == (1, 0)
    assert [(item["elective_id"], item["reason"]) for item in first.ambiguous] == [(gone.id, "backfilled_copy_edited_or_deleted")]
    second = await _converge(session, user, apply=True)
    assert second.mutations == 0 and [item["elective_id"] for item in second.ambiguous] == [gone.id]
    _assert_one_number(await _all_totals(session, user), 1)


# --- удалены ВСЕ копии (постоянный regression) ---------------------------------------------------------------


async def _old_backfill_workout_copy(session: AsyncSession, user, workout_set) -> int:
    """Legacy-тренировка + её копия старого backfill в транзакции плана (BACKFILL_AT): запись тренировки идёт через
    dual-write, затем ключ снимается и created_at выставляется так, как их оставил старый backfill."""
    workout = await _free_workout(session, user, workout_set, BASE - timedelta(days=5), 12)
    await session.execute(text("UPDATE workouts SET created_at = :c WHERE id = :i"), {"c": BACKFILL_AT - timedelta(days=5), "i": workout.id})
    await session.execute(text(
        "UPDATE training_sessions SET legacy_id = NULL, created_at = :c WHERE origin = 'legacy_backfill' AND legacy_id = :i",
    ), {"c": BACKFILL_AT, "i": workout.id})
    return workout.id


async def _all_copies_deleted(session: AsyncSession, telegram_id: int, *, with_workout: bool):
    """Штатный старый backfill (план и копии — одна транзакция) -> старое API удаляет ВСЕ копии факультативов."""
    user, workout_set = await _legacy_user(session, telegram_id)
    await _plan(session, user, BACKFILL_AT)
    if with_workout:
        await _old_backfill_workout_copy(session, user, workout_set)
    electives = [
        await _old_elective(session, user, kind, BASE + timedelta(hours=i), total, seq, BACKFILL_AT - timedelta(days=10))
        for i, (kind, total, seq) in enumerate(((ElectiveType.THREE_MINUTES, 9, [9]), (ElectiveType.VOLUME_TARGET, 30, None)))
    ]
    for elective in electives:
        await _old_delete(session, await _old_backfill_copy(session, elective))
    await _reload(session, user, *electives)
    return user, electives


async def _dry_apply_repeat(session: AsyncSession, user):
    before = await _elective_rows(session, user)
    dry = await _converge(session, user, apply=False)
    assert await _elective_rows(session, user) == before, "dry-run ничего не пишет"
    applied = await _converge(session, user, apply=True)
    assert applied.counts == dry.counts
    again = await _converge(session, user, apply=True)
    assert again.mutations == 0 and again.ambiguous == applied.ambiguous
    return applied


async def test_all_copies_deleted_after_standard_backfill_are_not_recreated(session: AsyncSession):
    """Штатный путь: старый backfill -> старое API удалило ВСЕ копии факультативов. План остаётся всегда (уникален,
    создан в транзакции копий, путей удаления нет ни в одной версии кода) -> факультативы не позже плана: копия не
    создаётся, привязки нет, оба в отчёте; dry-run/apply/повтор согласованы."""
    user, electives = await _all_copies_deleted(session, 991101, with_workout=False)
    applied = await _dry_apply_repeat(session, user)
    assert (applied.counts["bound"], applied.counts["elective_created"]) == (0, 0)
    # уцелевших копий транзакции плана нет -> перенос доказан только планом: «импорт не доказуем копией»
    assert [(i["elective_id"], i["reason"]) for i in applied.ambiguous] == [
        (e.id, "pre_migration_without_copy") for e in electives
    ]
    assert await _elective_rows(session, user) == []
    _assert_one_number(await _all_totals(session, user), 0)


async def test_all_copies_and_the_plan_gone_with_a_surviving_backfill_trace_is_guarded(session: AsyncSession):
    """Косвенного доказательства планом нет (план удалён — только ручным SQL, штатного пути нет), но уцелела копия
    legacy-тренировки из той же транзакции backfill: история не объяснима штатными писателями -> guard: ни копии,
    ни привязки по всем факультативам пользователя; повтор стабилен и после того, как сведение дало тренировке ключ."""
    user, electives = await _all_copies_deleted(session, 991102, with_workout=True)
    await session.execute(text("DELETE FROM plan_weeks WHERE training_plan_id IN (SELECT id FROM training_plans WHERE user_id = :u)"),
                          {"u": user.id})
    await session.execute(text("DELETE FROM training_plans WHERE user_id = :u"), {"u": user.id})
    await _reload(session, user, *electives)

    applied = await _dry_apply_repeat(session, user)
    assert (applied.counts["elective_created"], applied.counts["bound"]) == (0, 1)  # bound — копия тренировки
    assert {i["reason"] for i in applied.ambiguous} == {"nonstandard_copy_history"}
    assert [i["elective_id"] for i in applied.ambiguous] == [e.id for e in electives]
    assert all(i["evidence"].startswith("import_copy_without_plan:") for i in applied.ambiguous)
    assert await _elective_rows(session, user) == []
    _assert_one_number(await _all_totals(session, user), 1)  # только тренировка


async def test_traceless_deleted_copies_are_indistinguishable_from_never_imported(session: AsyncSession):
    """Известный пробел (STAGING_RC_REHEARSAL §8 «Фикс»): удалены все копии И план (только нештатно) и не осталось
    ни одного следа прогона. Такой пользователь в БД неотличим от ни разу не импортированного (первый импорт обязан
    создать копии) — без маркера прогона backfill их не разделить. Оба получают копии по штатному инварианту «плана
    нет -> backfill не проходил», и отчёт называет это основание, а не выдаёт его за доказательство."""
    deleted, deleted_electives = await _all_copies_deleted(session, 991103, with_workout=False)
    await session.execute(text("DELETE FROM training_plans WHERE user_id = :u"), {"u": deleted.id})
    never, _ = await _legacy_user(session, 991104)
    for i, (kind, total, seq) in enumerate(((ElectiveType.THREE_MINUTES, 9, [9]), (ElectiveType.VOLUME_TARGET, 30, None))):
        await _old_elective(session, never, kind, BASE + timedelta(hours=i), total, seq, BACKFILL_AT - timedelta(days=10))
    await _reload(session, deleted, never, *deleted_electives)

    def shape(report):
        return {k: v for k, v in report.counts.items() if v}, report.ambiguous

    first_deleted = await _dry_apply_repeat(session, deleted)
    first_never = await _dry_apply_repeat(session, never)
    assert shape(first_deleted) == shape(first_never)
    assert first_never.counts["elective_created"] == 2 and first_never.counts["elective_first_import_without_plan"] == 2


async def test_first_import_and_dual_write_are_unaffected(session: AsyncSession):
    """Доказанно корректный первый импорт: плана нет и нет ни одного следа прогона -> копии создаются; новая запись
    факультатива (dual-write, ключ сразу) в отчёт не попадает и не меняется."""
    user, _ = await _legacy_user(session, 991105)
    old = await _old_elective(session, user, ElectiveType.W_LADDER, BASE, 12, [4, 4, 4], BACKFILL_AT)
    new = await _old_elective(session, user, ElectiveType.THREE_MINUTES, BASE + timedelta(hours=1), 9, [9], BACKFILL_AT + timedelta(days=1))
    await LegacyConvergenceRepository(session).sync_elective(new)
    await session.execute(text("UPDATE training_sessions SET created_at = :c WHERE origin = 'legacy_elective' AND legacy_id = :i"),
                          {"c": new.created_at, "i": new.id})
    await _reload(session, user, old, new)
    applied = await _dry_apply_repeat(session, user)
    assert (applied.counts["elective_created"], applied.ambiguous) == (1, [])
    rows = await _elective_rows(session, user)
    assert sorted(r[2] for r in rows) == sorted([old.id, new.id]) and all(r[6] == 0 for r in rows)


# --- нештатная история: поздняя копия (форма прежней фикстуры test_single_history_migration) ---------------------


async def test_copy_outside_the_plan_transaction_guards_the_whole_user(session: AsyncSession):
    """Копия без ключа, созданная НЕ в транзакции плана (так её штатный backfill не пишет — см.
    docs/rehearsal/old_backfill_created_at.py; именно такой была копия 9005 в фикстуре test_single_history_migration
    до исправления created_at). Вывод «факультатив после плана никогда не переносился» недоказуем: у пользователя
    ни привязки (даже точной), ни новой копии; нативная/dual-write запись не затронута; повтор стабилен."""
    user, _ = await _legacy_user(session, 991201)
    await _plan(session, user, datetime(2026, 9, 14, 9, 0, tzinfo=UTC))
    early = await _old_elective(session, user, ElectiveType.THREE_MINUTES, datetime(2026, 9, 10, 9, 0, tzinfo=UTC), 9, [4, 3, 2],
                                datetime(2026, 9, 10, 9, 0, tzinfo=UTC))
    late_copy = await _old_backfill_copy(session, early, created_at=BACKFILL_AT)  # 2026-10-05, план — 2026-09-14
    after_plan = await _old_elective(session, user, ElectiveType.VOLUME_TARGET, datetime(2026, 9, 25, 9, 0, tzinfo=UTC), 40, None,
                                     datetime(2026, 9, 25, 9, 0, tzinfo=UTC))
    native = await _old_elective(session, user, ElectiveType.W_LADDER, BASE + timedelta(days=1), 12, [4, 4, 4], BACKFILL_AT + timedelta(days=1))
    await LegacyConvergenceRepository(session).sync_elective(native)
    await session.execute(text("UPDATE training_sessions SET created_at = :c WHERE origin = 'legacy_elective' AND legacy_id = :i"),
                          {"c": native.created_at, "i": native.id})
    await _reload(session, user, early, late_copy, after_plan, native)
    before = await _elective_rows(session, user)

    applied = await _dry_apply_repeat(session, user)
    assert (applied.counts["bound"], applied.counts["elective_created"], applied.mutations) == (0, 0, 0)
    assert [(i["elective_id"], i["reason"]) for i in applied.ambiguous] == [
        (early.id, "nonstandard_copy_history"), (after_plan.id, "nonstandard_copy_history"),
    ]
    assert applied.ambiguous[0]["evidence"] == f"unkeyed_elective_copy_outside_plan_transaction:[{late_copy.id}]"
    assert applied.ambiguous[0]["candidate_copy_ids"] == [late_copy.id]
    assert await _elective_rows(session, user) == before


# --- одинаковые timestamps -------------------------------------------------------------------------------


async def test_legitimate_identical_timestamps_bind_each_elective_to_its_own_copy(session: AsyncSession):
    """Два разных факультатива в одну и ту же секунду: каждый получает СВОЮ копию по полному содержимому;
    правка одной копии не переносит её на соседний факультатив."""
    user, _ = await _legacy_user(session, 991005)
    await _plan(session, user, BACKFILL_AT)
    created = BACKFILL_AT - timedelta(days=30)
    a = await _old_elective(session, user, ElectiveType.VOLUME_TARGET, BASE, 10, None, created)
    b = await _old_elective(session, user, ElectiveType.VOLUME_TARGET, BASE, 12, None, created)
    c = await _old_elective(session, user, ElectiveType.THREE_MINUTES, BASE, 12, [12], created)
    copy_a, copy_b, copy_c = [await _old_backfill_copy(session, e) for e in (a, b, c)]
    await _old_edit_value(session, copy_c, 13)  # правленая копия того же времени и той же суммы, что у соседа
    await _reload(session, user, a, b, c, copy_a, copy_b, copy_c)

    applied = await _converge(session, user, apply=True)
    assert (applied.counts["bound"], applied.counts["elective_created"]) == (2, 0)
    assert [(item["elective_id"], item["candidate_copy_ids"]) for item in applied.ambiguous] == [(c.id, [copy_c.id])]
    rows = {row[0]: row for row in await _elective_rows(session, user)}
    assert (rows[copy_a.id][2], rows[copy_b.id][2], rows[copy_c.id][2]) == (a.id, b.id, None)
    _assert_one_number(await _all_totals(session, user), 3)


async def test_identical_electives_are_interchangeable_and_one_deleted_copy_is_not_resurrected(session: AsyncSession):
    """Полностью одинаковые факультативы (время, формат, подходы): копии взаимозаменяемы — какая к какому
    привязана, не важно; удалённая копия одного из них не воскресает."""
    user, _ = await _legacy_user(session, 991006)
    await _plan(session, user, BACKFILL_AT)
    created = BACKFILL_AT - timedelta(days=30)
    twins = [await _old_elective(session, user, ElectiveType.THREE_MINUTES, BASE, 9, [9], created) for _ in range(2)]
    copies = [await _old_backfill_copy(session, e) for e in twins]
    await _old_delete(session, copies[1])
    await _reload(session, user)

    applied = await _converge(session, user, apply=True)
    assert (applied.counts["bound"], applied.counts["elective_created"], applied.counts["ambiguous_elective_without_copy"]) == (1, 0, 1)
    _assert_one_number(await _all_totals(session, user), 1)


async def test_exact_copy_older_than_the_elective_is_neither_bound_nor_duplicated(session: AsyncSession):
    """Копия не может быть старше своего факультатива: совпадение времени и содержимого с такой копией — не
    происхождение. Но и «копии нет» не доказано: ничего не привязывается и не создаётся — случай в отчёте."""
    user, _ = await _legacy_user(session, 991007)
    await _plan(session, user, BACKFILL_AT)
    elective = await _old_elective(session, user, ElectiveType.THREE_MINUTES, BASE, 9, [9], BACKFILL_AT + timedelta(days=1))
    older = await _old_backfill_copy(session, elective, created_at=BACKFILL_AT)
    await _reload(session, user, elective, older)

    dry = await _converge(session, user, apply=False)
    applied = await _converge(session, user, apply=True)
    assert dry.counts == applied.counts
    assert (applied.counts["bound"], applied.counts["elective_created"]) == (0, 0)
    assert [(i["elective_id"], i["reason"], i["candidate_copy_ids"]) for i in applied.ambiguous] == [
        (elective.id, "exact_copy_predates_elective", []),
    ]
    rows = await _elective_rows(session, user)
    assert [(r[0], r[2]) for r in rows] == [(older.id, None)]
    assert (await _converge(session, user, apply=True)).mutations == 0


# --- отчёт и скрипт ----------------------------------------------------------------------------------------


async def test_unclassified_copies_are_seen_by_dry_run_and_the_script_reports_unresolved(session: AsyncSession):
    """Копии без origin (старый код на новой схеме): dry-run видит их так же, как apply (dry-run == apply), а
    скрипт печатает каждый неразрешённый факультатив с причиной и кандидатами."""
    user, _ = await _legacy_user(session, 991008)
    await _plan(session, user, BACKFILL_AT)
    created = BACKFILL_AT - timedelta(days=30)
    kept = await _old_elective(session, user, ElectiveType.W_LADDER, BASE, 12, [4, 4, 4], created)
    edited = await _old_elective(session, user, ElectiveType.THREE_MINUTES, BASE + timedelta(hours=1), 9, [9], created)
    await _old_backfill_copy(session, kept, origin=None)
    edited_copy = await _old_backfill_copy(session, edited, origin=None)
    await _old_edit_value(session, edited_copy, 10)
    await _reload(session, user, kept, edited, edited_copy)
    user_id, edited_id, edited_copy_id = user.id, edited.id, edited_copy.id
    await session.commit()  # скрипт коммитит/откатывает транзакцию пользователя сам

    dry_unresolved: list[dict] = []
    dry = await converge_history_all(session, apply=False, user_ids=[user_id], unresolved=dry_unresolved)
    applied_unresolved: list[dict] = []
    applied = await converge_history_all(session, apply=True, user_ids=[user_id], unresolved=applied_unresolved)
    assert dry == applied and applied["elective_created"] == 0 and applied["bound"] == 1 and applied["classified"] == 2
    assert dry_unresolved == applied_unresolved and [i["elective_id"] for i in applied_unresolved] == [edited_id]
    lines = _render_unresolved(applied_unresolved)
    assert lines[0] == "Не разрешено (копия НЕ создана, ничего не привязано): 1"
    assert f"elective_id={edited_id}" in lines[1] and f"[{edited_copy_id}]" in lines[1] and "правлена или удалена" in lines[1]
    again = await converge_history_all(session, apply=True, user_ids=[user_id])
    assert not any(again[key] for key in ("classified", "bound", "created", "updated", "superseded", "elective_created"))
