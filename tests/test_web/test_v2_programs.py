"""GET /api/v2/programs (issue #165, волна 3) — каталог, read-only."""

from app.db.models import User
from app.db.models_program import Program, ProgressionStrategyProfile
from app.domain.multi_program import ProgramStructureType
from app.domain.progression_strategy import ProgressionStrategyType
from tests.test_web._v2_client import v2_get


async def test_list_programs_for_unknown_telegram_id_is_404(session):
    response = await v2_get(session, telegram_id=60001, path="/api/v2/programs")
    assert response.status_code == 404


async def test_list_programs_returns_catalog_with_strategy_type(session, user: User):
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Подтягивания", goal="test", structure_type=ProgramStructureType.RECURRING,
        category="pullups", progression_strategy_id=profile.id, config={},
    )
    session.add(program)
    await session.flush()

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/programs")

    assert response.status_code == 200
    programs = response.json()["programs"]
    assert len(programs) == 1
    assert programs[0]["name"] == "Подтягивания"
    assert programs[0]["progression_strategy_type"] == "step"


async def test_list_programs_without_strategy_reports_none(session, user: User):
    program = Program(
        name="Без стратегии", goal="test", structure_type=ProgramStructureType.SINGLE_LESSON, config={},
    )
    session.add(program)
    await session.flush()

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/programs")

    assert response.status_code == 200
    assert response.json()["programs"][0]["progression_strategy_type"] is None
