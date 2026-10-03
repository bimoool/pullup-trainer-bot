"""POST /api/v2/program-inclusions/{id}/progression/preview|apply (issue
#165, продолжение волны 3, раздел 10.6 docs/plan-and-specs.md "Изменится
план"): правка исторической STEP-сессии пересчитывает ВСЮ цепочку заново
от ProgramInclusion.initial_progression_state (см. app.services.
progression_cascade). Сценарий сверху — тот самый E2E из раздела 15
("Правка вчерашней сессии → лист preview с изменениями → Применить → target
следующей сессии изменился; Оставить → не изменился"), выраженный через
HTTP: preview/apply НЕ мутируют/мутируют progression_state соответственно,
повторный preview после apply сходится к пустому diff (реплей теперь
совпадает с новым персистентным состоянием — само по себе доказательство,
что реплей корректен, а не только "что-то вернул")."""

from app.db.models_program import Exercise, Program, ProgressionStrategyProfile
from app.domain.multi_program import MetricType, ProgramStructureType
from app.domain.progression_strategy import ProgressionStrategyType
from tests.test_web._v2_client import v2_get, v2_post


async def _make_step_program(session, *, category: str = "cascade_sessions") -> Program:
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Синтетика каскада", goal="test", structure_type=ProgramStructureType.RECURRING,
        category=category, progression_strategy_id=profile.id,
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
    )
    session.add(program)
    await session.flush()
    session.add_all([
        Exercise(name="Блок A", metric_type=MetricType.REPS, category=category, subcategory="block_a"),
        Exercise(name="Блок Б", metric_type=MetricType.REPS, category=category, subcategory="block_b"),
    ])
    await session.flush()
    return program


async def _create_inclusion(session, telegram_id: int, program_id: int) -> dict:
    response = await v2_post(
        session, telegram_id=telegram_id, path="/api/v2/program-inclusions", payload={"program_id": program_id},
    )
    assert response.status_code == 200
    return response.json()


def _exercise_ids_by_role(inclusion: dict) -> dict[str, int]:
    return {e["role"]: e["exercise_id"] for e in inclusion["snapshot"]["exercises"]}


def _sets_block(exercise_id: int, working_reps: list[int], max_reps: int) -> dict:
    sets = [
        {"set_number": i + 1, "metric_type": "reps", "value": str(r), "unit": "reps"}
        for i, r in enumerate(working_reps)
    ]
    sets.append({
        "set_number": len(working_reps) + 1, "metric_type": "reps", "value": str(max_reps), "unit": "reps",
        "is_max_set": True,
    })
    return {"exercise_id": exercise_id, "sets": sets}


async def _record_session(session, telegram_id: int, inclusion_id: int, performed_at: str, roles: dict) -> dict:
    response = await v2_post(
        session, telegram_id=telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "performed_at": performed_at, "program_inclusion_id": inclusion_id,
            "blocks": [
                _sets_block(roles["block_a"], [11, 11, 11], 12),
                _sets_block(roles["block_b"], [4, 4, 4, 4], 4),
            ],
        },
    )
    assert response.status_code == 200
    return response.json()


async def _progression_state(session, telegram_id: int, inclusion_id: int) -> dict:
    plan_response = await v2_get(session, telegram_id=telegram_id, path="/api/v2/plan")
    inclusions = plan_response.json()["plan"]["program_inclusions"]
    return next(i for i in inclusions if i["id"] == inclusion_id)["progression_state"]


async def test_preview_for_unknown_inclusion_is_404(session, user):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions/999999/progression/preview",
        payload={"edited_session_id": 1},
    )
    assert response.status_code == 404


async def test_preview_for_unknown_session_is_404(session, user):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)

    response = await v2_post(
        session, telegram_id=user.telegram_id,
        path=f"/api/v2/program-inclusions/{inclusion['id']}/progression/preview",
        payload={"edited_session_id": 999999},
    )
    assert response.status_code == 404


async def test_preview_for_non_step_inclusion_is_422(session, user):
    program = Program(
        name="Без стратегии", goal="test", structure_type=ProgramStructureType.SINGLE_LESSON,
        category="no_strategy_cascade", config={},
    )
    session.add(program)
    await session.flush()
    exercise = Exercise(name="Одиночное", metric_type=MetricType.REPS, category="no_strategy_cascade")
    session.add(exercise)
    await session.flush()
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    assert inclusion["progression_state"] == {}

    response = await v2_post(
        session, telegram_id=user.telegram_id,
        path=f"/api/v2/program-inclusions/{inclusion['id']}/progression/preview",
        payload={"edited_session_id": 1},
    )
    assert response.status_code == 422


async def test_preview_with_no_value_change_returns_empty_deltas(session, user):
    """"Оставить как есть" может быть буквальным no-op — preview без
    заполненных block_a/block_b (обе стороны None) реплеит цепочку БЕЗ
    подстановки, должен совпасть с уже персистентным состоянием."""
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    roles = _exercise_ids_by_role(inclusion)
    recorded = await _record_session(session, user.telegram_id, inclusion["id"], "2026-01-05T10:00:00Z", roles)

    response = await v2_post(
        session, telegram_id=user.telegram_id,
        path=f"/api/v2/program-inclusions/{inclusion['id']}/progression/preview",
        payload={"edited_session_id": recorded["id"]},
    )

    assert response.status_code == 200
    assert response.json()["deltas"] == []


async def test_preview_and_apply_cascade_recomputes_full_chain_and_converges(session, user):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    roles = _exercise_ids_by_role(inclusion)

    session1 = await _record_session(session, user.telegram_id, inclusion["id"], "2026-01-05T10:00:00Z", roles)
    await _record_session(session, user.telegram_id, inclusion["id"], "2026-01-08T10:00:00Z", roles)

    state_before = await _progression_state(session, user.telegram_id, inclusion["id"])

    # Правка блока A первой сессии на более сильный результат — растит
    # цель дальше по всей последующей цепочке, не только у самой сессии.
    edited_block_a = [
        {"set_number": 1, "metric_type": "reps", "value": "16", "unit": "reps"},
        {"set_number": 2, "metric_type": "reps", "value": "16", "unit": "reps"},
        {"set_number": 3, "metric_type": "reps", "value": "16", "unit": "reps"},
        {"set_number": 4, "metric_type": "reps", "value": "18", "unit": "reps", "is_max_set": True},
    ]

    preview = await v2_post(
        session, telegram_id=user.telegram_id,
        path=f"/api/v2/program-inclusions/{inclusion['id']}/progression/preview",
        payload={"edited_session_id": session1["id"], "block_a": edited_block_a},
    )
    assert preview.status_code == 200
    deltas = preview.json()["deltas"]
    assert deltas  # правка достаточно сильная, чтобы сдвинуть итоговую цель
    block_a_delta = next(d for d in deltas if d["exercise"] == "block_a")
    assert block_a_delta["before"] == state_before["block_a"]["target"]
    assert block_a_delta["after"] > block_a_delta["before"]  # сильнее -> цель выше, не ниже

    # preview НЕ имеет побочных эффектов — persisted-состояние не тронуто.
    state_after_preview = await _progression_state(session, user.telegram_id, inclusion["id"])
    assert state_after_preview == state_before

    apply_response = await v2_post(
        session, telegram_id=user.telegram_id,
        path=f"/api/v2/program-inclusions/{inclusion['id']}/progression/apply",
        payload={"edited_session_id": session1["id"], "block_a": edited_block_a},
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["deltas"] == deltas

    state_after_apply = await _progression_state(session, user.telegram_id, inclusion["id"])
    assert state_after_apply["block_a"]["target"] == block_a_delta["after"]

    # Повторный preview с ТЕМИ ЖЕ правками теперь сходится к пустому diff —
    # реплей "с подстановкой" и "без" совпадают, потому что persisted-
    # состояние САМО стало результатом этой подстановки (доказательство
    # корректности реплея, не просто "апи что-то отдал").
    preview_again = await v2_post(
        session, telegram_id=user.telegram_id,
        path=f"/api/v2/program-inclusions/{inclusion['id']}/progression/preview",
        payload={"edited_session_id": session1["id"], "block_a": edited_block_a},
    )
    assert preview_again.status_code == 200
    assert preview_again.json()["deltas"] == []
