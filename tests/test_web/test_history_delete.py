"""DELETE /api/history/{workout_id} (issue #146) — удаление тренировок.

Два пути (app/services/workout_deletion.py):
- бэкдейт/свободные (participates_in_cascade=False) — просто исчезают,
  пересчитывать нечего (нет sequence_number/цепочки).
- обычные каскадные — решение Кирилла, вариант A: удаление пересчитывает
  каскад для всей цепочки, начиная с позиции удалённой записи
  (WorkoutRepository.recalculate_cascade_on_delete). Числа в
  test_delete_history_workout_recalculates_cascade_for_middle_workout
  посчитаны руками по формулам app.domain.progression (см. комментарии в
  самом тесте), не выведены из тестируемого кода — тот же стиль
  тестирования, что и в test_history_edit.py."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.models import BlockType, User, Workout, WorkoutSet
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app
from tests.test_web.test_history_edit import _FakeInitData, _FakeWebAppUser, _make_chain

BAND_VALUE = Decimal("15.0")
WEIGHT_VALUE = Decimal("10.0")


def _override_dependencies(session, telegram_id: int) -> None:
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def _delete_history_raw(session, telegram_id: int, workout_id: int):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.delete(f"/api/history/{workout_id}")
    finally:
        app.dependency_overrides.clear()


async def _get_history_list_raw(session, telegram_id: int):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/api/history")
    finally:
        app.dependency_overrides.clear()


async def _make_three_workout_chain(session, *, telegram_id: int) -> tuple[User, WorkoutSet, list[Workout]]:
    """Три обычные (каскадные) тренировки подряд, оба блока на BODYWEIGHT —
    специально НЕ на WEIGHT: блок Б на WEIGHT чередовал бы каждую вторую
    тренировку сета в "тяжёлую" (issue #97, workouts_completed_in_set % 2),
    что заморозило бы её прогрессию и сломало бы ручной расчёт чисел ниже.
    working_reps/max_reps подобраны так, чтобы прогрессия росла монотонно
    (без слабых/застойных веток) — числа воспроизведены вручную по
    app.domain.progression.recalculate_volume_block/recalculate_target в
    самом тесте, не читаны из результата тестируемого кода."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=now - timedelta(days=20), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workouts = WorkoutRepository(session)

    w1 = await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=15),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )
    w2 = await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=10),
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=25),
        block_b_reps=BlockLog(working_reps=(6, 6, 6, 6), max_reps=8),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )
    w3 = await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(21, 21, 21), max_reps=23),
        block_b_reps=BlockLog(working_reps=(6, 6, 6, 6), max_reps=8),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )
    return user, workout_set, [w1, w2, w3]


async def test_history_entry_marks_all_workouts_as_deletable(session):
    user, workouts = await _make_chain(session, telegram_id=60001)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )

    response = await _get_history_list_raw(session, telegram_id=user.telegram_id)
    assert response.status_code == 200
    items = {item["workout_id"]: item for item in response.json()["items"]}
    # issue #146, решение Кирилла (вариант A): и каскадные, и бэкдейт/
    # свободные записи теперь удаляемы — is_deletable больше не совпадает
    # только с is_backdated.
    assert items[workouts[0].id]["is_deletable"] is True
    backdated_id = next(iter(set(items) - {w.id for w in workouts}))
    assert items[backdated_id]["is_deletable"] is True


async def test_delete_history_workout_for_unknown_telegram_id_is_404(session):
    _user, workouts = await _make_chain(session, telegram_id=60002)
    response = await _delete_history_raw(session, telegram_id=99999, workout_id=workouts[0].id)
    assert response.status_code == 404


async def test_delete_history_workout_for_foreign_workout_is_404(session):
    _user, workouts = await _make_chain(session, telegram_id=60003)
    other = await UserRepository(session).create(telegram_id=60004, username="other")
    response = await _delete_history_raw(session, telegram_id=other.telegram_id, workout_id=workouts[0].id)
    assert response.status_code == 404


async def test_delete_history_workout_rejects_started_workout(session):
    """STARTED (не завершённая) живая тренировка — participates_in_cascade
    по умолчанию True, но sequence_number ещё не выставлен (проставляется
    только complete_workout). recalculate_cascade_on_delete не найдёт такую
    запись в _cascade_chain (она фильтрует по sequence_number IS NOT NULL) —
    _history_is_editable отсекает её раньше, тем же условием, что и для
    правки (issue #52)."""
    user, _workouts = await _make_chain(session, telegram_id=60009)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    started = await WorkoutRepository(session).start_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC),
    )

    response = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=started.id)
    assert response.status_code == 400

    still_there = await WorkoutRepository(session).get_by_id(started.id)
    assert still_there is not None


async def test_delete_history_workout_recalculates_cascade_for_middle_workout(session):
    """Удаление СРЕДНЕЙ каскадной тренировки (issue #146, решение Кирилла —
    вариант A). Цепочка w1 -> w2 -> w3, удаляем w2, w3 должна пересчитаться
    так, будто цепочка сразу была w1 -> w3.

    Ручной расчёт (app.domain.progression, BODYWEIGHT-ветка
    recalculate_volume_block/_compute_raw_target, STEP_PCT=0.05):

    w1: A target_before=10 (VOLUME_BLOCK.base_target), working=(10,10,10)
        max=12 -> delta=2>0, avg=10, step=max(1, ceil(10*0.05))=1,
        target_after_a=round(10)+1=11; volume_a=10*3+12=42.
        B target_before=3 (STRENGTH_BLOCK.base_target), working=(3,3,3,3)
        max=4 -> delta=1>0, avg=3, step=max(1, ceil(3*0.05))=1,
        target_after_b=round(3)+1=4; volume_b=3*4+4=16.

    w2 (удаляется): A target_before=11, working=(20,20,20) max=25 ->
        delta=14>0, avg=20, step=max(1, ceil(11*0.05))=1,
        target_after_a=round(20)+1=21 (< VOLUME_TARGET_CEILING=33, потолок
        не задет). B target_before=4, working=(6,6,6,6) max=8 -> delta=4>0,
        avg=6, step=max(1, ceil(4*0.05))=1, target_after_b=round(6)+1=7
        (working_reps=6 < equipment_change_threshold=7, снаряд не меняется).

    w3: те же самые working/max, что были записаны (7, при удалении НЕ
        меняются — меняется только target_before/target_after от нового
        стартового состояния). После удаления w2 стартовое состояние для
        w3 — это состояние ПОСЛЕ w1 (_preceding_chain_state(chain, 1)):
        target_before_a=11 (вместо исходных 21 от w2), target_before_b=4
        (вместо исходных 7).
        A: working=(21,21,21) max=23, target=11 -> delta=12>0, avg=21,
           step=max(1, ceil(11*0.05))=1, target_after_a=round(21)+1=22
           (исходно, от target=21, было target_after_a=23 — другое число,
           наглядно доказывает пересчёт).
        B: working=(6,6,6,6) max=8, target=4 -> delta=4>0, avg=6,
           step=max(1, ceil(4*0.05))=1, target_after_b=round(6)+1=7 —
           совпадает с исходным (7) чисто арифметически: step=1 что при
           target_before=4, что при 7 (ceil(x*0.05)=1 для любого target от
           1 до 20) — сам target_before всё равно меняется с 7 на 4,
           проверяется отдельно."""
    user, workout_set, (_w1, w2, w3) = await _make_three_workout_chain(session, telegram_id=60010)
    await session.refresh(workout_set)
    assert workout_set.workouts_completed == 3

    response = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=w2.id)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    assert await WorkoutRepository(session).get_by_id(w2.id) is None

    archived_workouts = (
        await session.execute(
            text("SELECT count(*) FROM workouts_archive_admin_reset WHERE id = :wid"), {"wid": w2.id},
        )
    ).scalar()
    assert archived_workouts == 1
    archived_blocks = (
        await session.execute(
            text("SELECT count(*) FROM blocks_archive_admin_reset WHERE workout_id = :wid"), {"wid": w2.id},
        )
    ).scalar()
    assert archived_blocks == 2

    w3_reloaded = await WorkoutRepository(session).get_by_id(w3.id)
    block_a = next(b for b in w3_reloaded.blocks if b.block_type == BlockType.A)
    block_b = next(b for b in w3_reloaded.blocks if b.block_type == BlockType.B)
    assert (block_a.target_before, block_a.target_after) == (11, 22)
    assert (block_b.target_before, block_b.target_after) == (4, 7)
    assert block_a.equipment_changed is False
    assert block_b.equipment_changed is False

    # sequence_number цепочки не должен оставлять дыру (иначе следующая
    # живая тренировка получила бы len(chain)+1, коллизия с уже занятым
    # номером — см. докстринг recalculate_cascade_on_delete).
    assert w3_reloaded.sequence_number == 2

    # complete_workout инкрементировал workouts_completed трижды (w1/w2/w3)
    # — удаление w2 обязано откатить один инкремент, тот же принцип, что и
    # для бэкдейта (issue #97, чётность is_heavy последующих тренировок).
    await session.refresh(workout_set)
    assert workout_set.workouts_completed == 2


async def test_delete_history_workout_last_in_chain_has_nothing_to_recalculate(session):
    """Удаление ПОСЛЕДНЕЙ тренировки цепочки — following пуст,
    recalculate_cascade не вызывается вовсе, соседние (w1) sequence_number
    не трогается."""
    user, workout_set, (w1, w2, w3) = await _make_three_workout_chain(session, telegram_id=60011)

    response = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=w3.id)
    assert response.status_code == 200

    assert await WorkoutRepository(session).get_by_id(w3.id) is None
    w1_reloaded = await WorkoutRepository(session).get_by_id(w1.id)
    w2_reloaded = await WorkoutRepository(session).get_by_id(w2.id)
    assert w1_reloaded.sequence_number == 1
    assert w2_reloaded.sequence_number == 2

    await session.refresh(workout_set)
    assert workout_set.workouts_completed == 2


async def test_delete_history_workout_removes_backdated_entry_and_archives_it(session):
    user, _workouts = await _make_chain(session, telegram_id=60006)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    completed_before = workout_set.workouts_completed
    backdated = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )
    await session.refresh(workout_set)
    assert workout_set.workouts_completed == completed_before + 1

    response = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    assert await WorkoutRepository(session).get_by_id(backdated.id) is None

    archived_workouts = (
        await session.execute(
            text("SELECT count(*) FROM workouts_archive_admin_reset WHERE id = :wid"), {"wid": backdated.id},
        )
    ).scalar()
    assert archived_workouts == 1
    archived_blocks = (
        await session.execute(
            text("SELECT count(*) FROM blocks_archive_admin_reset WHERE workout_id = :wid"), {"wid": backdated.id},
        )
    ).scalar()
    assert archived_blocks == 2

    # record_backdated_workout инкрементировал workouts_completed при
    # создании — удаление обязано откатить это (issue #146), иначе чётность
    # is_heavy (issue #97) для всех последующих тренировок блока Б навсегда
    # сдвинется на единицу.
    await session.refresh(workout_set)
    assert workout_set.workouts_completed == completed_before


async def test_delete_history_workout_removes_free_entry_without_touching_workout_set(session):
    user, _workouts = await _make_chain(session, telegram_id=60007)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    completed_before = workout_set.workouts_completed
    free_entry = await WorkoutRepository(session).record_free_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=1),
        block_a_reps=BlockLog(working_reps=(20,), max_reps=25),
        equipment_type=EquipmentType.BODYWEIGHT,
    )

    response = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=free_entry.id)
    assert response.status_code == 200

    assert await WorkoutRepository(session).get_by_id(free_entry.id) is None
    await session.refresh(workout_set)
    assert workout_set.workouts_completed == completed_before


async def test_delete_history_workout_is_404_on_second_call(session):
    user, _workouts = await _make_chain(session, telegram_id=60008)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    backdated = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )

    first = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id)
    assert first.status_code == 200
    second = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id)
    assert second.status_code == 404
