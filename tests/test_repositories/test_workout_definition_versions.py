"""workout_definition_versions на реальном Postgres (issue #303): append-only версии (B1),
version_no + 1, W5 по всей истории (B3), снисходительное чтение истории, неизменяемость,
точный roundtrip W-лесенки/MAX/поподходного отдыха, снимок."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.models_program import Complex, ComplexItem, Exercise
from app.db.repositories.workout_definitions import WorkoutDefinitionRepository
from app.domain import workout_definition as wd
from app.domain.multi_program import MetricType
from app.domain.workout_definition import (
    SetKind,
    WorkoutContentError,
    content_hash,
    describe,
    describe_rest,
    normalize,
    snapshot_from_dict,
    snapshot_to_dict,
    stored_content_hash,
)
from app.services.workout_definition import WorkoutDefinitionService

W_LADDER = [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5]
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


async def _workout(session, user=None, *, title="Тест") -> tuple[Complex, Exercise]:
    exercise = Exercise(
        name="Подтягивания", display_name="Подтягивания", metric_type=MetricType.REPS,
        category="Подтягивания", source_type="system",
    )
    complex_ = Complex(
        name=title, source_type="user" if user else "system", owner_user_id=user.id if user else None,
    )
    session.add_all([exercise, complex_])
    await session.flush()
    return complex_, exercise


def _ladder(exercise_id: int, title: str = "W-лесенка") -> dict:
    sets = [{"kind": "reps", "target_reps": r, "rest_after_seconds": 10} for r in W_LADDER]
    del sets[-1]["rest_after_seconds"]
    return {"title": title, "blocks": [{"key": "A", "exercise_id": exercise_id, "sets": sets}]}


async def test_unchanged_save_creates_no_version_changed_save_increments(session):
    complex_, exercise = await _workout(session)
    repo = WorkoutDefinitionRepository(session)
    first, created = await repo.save_content(complex_.id, normalize(_ladder(exercise.id)))
    assert created and first.version_no == 1

    same, created_again = await repo.save_content(complex_.id, normalize(_ladder(exercise.id)))
    assert not created_again and same.id == first.id

    changed, created_changed = await repo.save_content(complex_.id, normalize(_ladder(exercise.id, "W-лесенка 2")))
    assert created_changed and changed.version_no == 2
    assert [v.version_no for v in await repo.list_versions(complex_.id)] == [1, 2]
    await session.refresh(complex_)
    assert complex_.current_version_id == changed.id


async def test_w_ladder_max_and_rests_roundtrip_exactly_through_db(session):
    complex_, exercise = await _workout(session)
    raw = {"title": "Смесь", "blocks": [
        _ladder(exercise.id)["blocks"][0],
        {"key": "M", "exercise_id": exercise.id, "sets": [
            {"kind": "max_reps", "rest_after_seconds": 180},
            {"kind": "max_reps", "rest_after_seconds": 120},
            {"kind": "max_reps", "rest_after_seconds": 60},
            {"kind": "max_reps"},
        ]},
    ]}
    repo = WorkoutDefinitionRepository(session)
    saved, _ = await repo.save_content(complex_.id, normalize(raw))
    session.expire_all()
    stored = (await session.execute(
        text("SELECT content FROM workout_definition_versions WHERE id = :id"), {"id": saved.id},
    )).scalar_one()
    assert [s["target_reps"] for s in stored["blocks"][0]["sets"]] == W_LADDER
    assert [s["target_reps"] for s in stored["blocks"][1]["sets"]] == [None, None, None, None]
    assert [s["rest_after_seconds"] for s in stored["blocks"][1]["sets"]] == [180, 120, 60, None]

    read = await repo.get_version(saved.id)
    ladder, maximum = read.content.blocks
    assert [s.target_reps for s in ladder.sets] == W_LADDER
    assert describe(ladder) == "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5"
    assert all(s.kind is SetKind.MAX_REPS and s.target_reps is None for s in maximum.sets)
    assert describe(maximum) == "Максимум × 4"
    assert describe_rest(maximum) == "отдых 3:00 → 2:00 → 1:00"


async def test_versions_are_immutable_at_db_level(session):
    complex_, exercise = await _workout(session)
    saved, _ = await WorkoutDefinitionRepository(session).save_content(complex_.id, normalize(_ladder(exercise.id)))
    await session.commit()
    with pytest.raises(DBAPIError, match="immutable"):
        await session.execute(
            text("UPDATE workout_definition_versions SET content_hash = 'x' WHERE id = :id"), {"id": saved.id},
        )
    await session.rollback()


async def test_old_version_and_snapshot_stay_renderable_after_new_version(session):
    complex_, exercise = await _workout(session)
    service = WorkoutDefinitionService(session)
    old, _ = await service.save(complex_.id, _ladder(exercise.id), visible_exercise_ids=None)
    old_snapshot = snapshot_to_dict(await service.build_snapshot(old.id, resolved_at=NOW))

    exercise.display_name = "Подтягивания (новое имя)"
    new, created = await service.save(
        complex_.id, {"title": "17 × 3", "blocks": [{"key": "A", "exercise_id": exercise.id, "sets": 17, "reps": 3}]},
        visible_exercise_ids=None,
    )
    assert created and new.version_no == 2

    old_again = await WorkoutDefinitionRepository(session).get_version(old.id)
    assert describe(old_again.content.blocks[0]) == "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5"
    restored = snapshot_from_dict(old_snapshot)
    assert restored.version_no == 1 and restored.title == "W-лесенка"
    assert restored.blocks[0].exercise_display_name == "Подтягивания"
    assert describe(restored.blocks[0]) == "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5"

    new_snapshot = await service.build_snapshot(new.id, resolved_at=NOW)
    assert new_snapshot.blocks[0].exercise_display_name == "Подтягивания (новое имя)"
    assert describe(new_snapshot.blocks[0]) == "17 × 3"


async def test_a_b_a_appends_v3_monotonically_and_resaving_current_is_noop(session):
    """Решение владельца B1: версии append-only и монотонны. A → B → A = v1, v2, v3 (а не
    возврат указателя на v1); повторное A при текущей v3 = A — ничего не создаёт."""
    complex_, exercise = await _workout(session)
    repo = WorkoutDefinitionRepository(session)
    a = normalize(_ladder(exercise.id))
    v1, created1 = await repo.save_content(complex_.id, a)
    v2, created2 = await repo.save_content(complex_.id, normalize(_ladder(exercise.id, "B")))
    v3, created3 = await repo.save_content(complex_.id, a)
    assert (created1, created2, created3) == (True, True, True)
    assert (v1.version_no, v2.version_no, v3.version_no) == (1, 2, 3)
    assert v3.id not in (v1.id, v2.id)
    assert v3.content_hash == v1.content_hash
    await session.refresh(complex_)
    assert complex_.current_version_id == v3.id
    max_no = (await session.execute(
        text("SELECT MAX(version_no) FROM workout_definition_versions WHERE workout_definition_id = :id"),
        {"id": complex_.id},
    )).scalar_one()
    assert max_no == v3.version_no == 3

    again, created_again = await repo.save_content(complex_.id, a)
    assert not created_again and again.id == v3.id
    assert [v.version_no for v in await repo.list_versions(complex_.id)] == [1, 2, 3]
    await session.refresh(complex_)
    assert complex_.current_version_id == v3.id


async def test_content_hash_is_not_unique_per_definition_in_schema(session):
    unique_indexes = (await session.execute(text(
        "SELECT indexdef FROM pg_indexes WHERE tablename = 'workout_definition_versions' AND indexdef LIKE '%UNIQUE%'"
    ))).scalars().all()
    assert not any("content_hash" in index for index in unique_indexes), unique_indexes
    assert any("version_no" in index for index in unique_indexes), unique_indexes


async def test_w5_against_all_prior_versions_removed_key_cannot_be_reused_for_other_exercise(session, user):
    """Блок удалён в одной версии, ключ позже возвращён под другим упражнением — отказ W5,
    хотя в ТЕКУЩЕЙ версии ключа нет (review B3)."""
    complex_, exercise = await _workout(session, user)
    other = Exercise(name="Другое", metric_type=MetricType.REPS, category="user", source_type="system")
    session.add(other)
    await session.flush()
    service = WorkoutDefinitionService(session)
    both = {"title": "T", "blocks": [
        {"key": "A", "exercise_id": exercise.id, "sets": 1, "reps": 1},
        {"key": "B", "exercise_id": other.id, "sets": 1, "reps": 1},
    ]}
    await service.save(complex_.id, both, visible_exercise_ids=None)
    await service.save(complex_.id, {"title": "T", "blocks": [both["blocks"][1]]}, visible_exercise_ids=None)
    with pytest.raises(WorkoutContentError) as exc:
        await service.save(complex_.id, {"title": "T", "blocks": [
            {"key": "A", "exercise_id": other.id, "sets": 2, "reps": 2},
        ]}, visible_exercise_ids=None)
    assert exc.value.code == "W5"
    assert len(await WorkoutDefinitionRepository(session).list_versions(complex_.id)) == 2  # ничего не записано
    restored, created = await service.save(complex_.id, {"title": "T", "blocks": [
        {"key": "A", "exercise_id": exercise.id, "sets": 2, "reps": 2},
    ]}, visible_exercise_ids=None)
    assert created and restored.version_no == 3  # тот же ключ — то же упражнение: можно


async def test_v1_item_id_reused_for_another_exercise_gets_a_distinct_key(session, user):
    """V1-строка удалена (блока нет), потом строка с тем же id появляется с другим упражнением —
    ключ другой (i<item>e<exercise>), прежняя семантическая идентичность не перехвачена."""
    complex_, exercise = await _workout(session, user)
    other = Exercise(name="Другое", metric_type=MetricType.REPS, category="user", source_type="system")
    session.add(other)
    await session.flush()
    protocol = {"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 10}, "rest_seconds": 90}
    keeper = ComplexItem(complex_id=complex_.id, exercise_id=exercise.id, order_index=0, sets=0, protocol=protocol)
    removed = ComplexItem(complex_id=complex_.id, exercise_id=exercise.id, order_index=1, sets=0, protocol=protocol)
    session.add_all([keeper, removed])
    await session.flush()
    repo = WorkoutDefinitionRepository(session)
    await repo.sync_from_head(complex_.id)
    removed_id = removed.id
    await session.execute(text("DELETE FROM complex_items WHERE id = :id"), {"id": removed_id})
    await repo.sync_from_head(complex_.id)
    await session.execute(
        text(
            "INSERT INTO complex_items (id, complex_id, exercise_id, order_index, sets, protocol) "
            "VALUES (:id, :complex_id, :exercise_id, 1, 0, CAST(:protocol AS jsonb))"
        ),
        {"id": removed_id, "complex_id": complex_.id, "exercise_id": other.id, "protocol": json.dumps(protocol)},
    )
    _, created, reason = await repo.sync_from_head(complex_.id)
    assert created and reason is None

    keys: dict[str, set[int]] = {}
    for version in await repo.list_versions(complex_.id):
        for block in version.content.blocks:
            keys.setdefault(block.key, set()).add(block.exercise_id)
    assert keys == {
        f"i{keeper.id}e{exercise.id}": {exercise.id},
        f"i{removed_id}e{exercise.id}": {exercise.id},
        f"i{removed_id}e{other.id}": {other.id},
    }


async def test_historical_version_survives_later_writer_schema_evolution(session, monkeypatch):
    """Адверсариально: v1 записана; позже писатель добавляет необязательное поле в хранимую форму.
    Старая строка читается и рендерится, её исходный хеш остаётся валидным (никакого
    hash_mismatch из-за сегодняшнего normalize()/to_dict()); новая — тоже читается."""
    complex_, exercise = await _workout(session)
    repo = WorkoutDefinitionRepository(session)
    old, _ = await repo.save_content(complex_.id, normalize(_ladder(exercise.id)))
    old_hash, complex_id = old.content_hash, complex_.id

    original_block_to_dict = wd._block_to_dict
    monkeypatch.setattr(wd, "_block_to_dict", lambda block: {**original_block_to_dict(block), "notes": None})
    new, created = await repo.save_content(complex_.id, normalize(_ladder(exercise.id, "После эволюции")))
    assert created and "notes" in (await session.execute(
        text("SELECT content FROM workout_definition_versions WHERE id = :id"), {"id": new.id},
    )).scalar_one()["blocks"][0]

    session.expire_all()
    old_again = await repo.get_version(old.id)
    assert old_again.content_hash == old_hash
    assert stored_content_hash((await session.execute(
        text("SELECT content FROM workout_definition_versions WHERE id = :id"), {"id": old.id},
    )).scalar_one()) == old_hash
    assert describe(old_again.content.blocks[0]) == "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5"
    # Старый путь (сегодняшний сериализатор → хеш) объявил бы эту строку испорченной, а сегодняшний
    # строгий normalize() её бы вовсе не принял (незнакомого ему поля у неё нет, но у новых — есть):
    assert content_hash(old_again.content) != old_hash
    assert [v.version_no for v in await repo.list_versions(complex_id)] == [1, 2]
    view = (await WorkoutDefinitionService(session).prescriptions([complex_id]))[complex_id]
    assert view.version.id == new.id


async def test_service_save_enforces_w5_and_w6(session, user):
    complex_, exercise = await _workout(session, user)
    service = WorkoutDefinitionService(session)
    with pytest.raises(WorkoutContentError) as exc:
        await service.save(complex_.id, _ladder(exercise.id), visible_exercise_ids=set())
    assert exc.value.code == "W6"
    await service.save(complex_.id, _ladder(exercise.id), visible_exercise_ids={exercise.id})
    other = Exercise(name="Другое", metric_type=MetricType.REPS, category="user", source_type="system")
    session.add(other)
    await session.flush()
    with pytest.raises(WorkoutContentError) as exc:
        await service.save(complex_.id, _ladder(other.id), visible_exercise_ids={other.id})
    assert exc.value.code == "W5"


async def test_sync_head_follows_v1_items_and_clears_on_empty(session, user):
    complex_, exercise = await _workout(session, user)
    session.add(ComplexItem(
        complex_id=complex_.id, exercise_id=exercise.id, order_index=0, sets=0,
        protocol={"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 10}, "rest_seconds": 90},
    ))
    await session.flush()
    repo = WorkoutDefinitionRepository(session)
    version_id, created, reason = await repo.sync_from_head(complex_.id)
    assert created and reason is None
    again_id, created_again, _ = await repo.sync_from_head(complex_.id)
    assert again_id == version_id and not created_again
    assert describe((await repo.get_version(version_id)).content.blocks[0]) == "3 × 10"

    await session.execute(text("DELETE FROM complex_items WHERE complex_id = :id"), {"id": complex_.id})
    cleared_id, _, reason = await repo.sync_from_head(complex_.id)
    assert cleared_id is None and reason is not None
    await session.refresh(complex_)
    assert complex_.current_version_id is None
    assert len(await repo.list_versions(complex_.id)) == 1  # история версий не удаляется
