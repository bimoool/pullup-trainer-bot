"""Решение владельца 2026-10-07: системная программа «Подтягивания» бесплатна навсегда — без Premium (истёкший
триал / нет подписки) её можно открыть, добавить в план, получить тренировки недели, стартовать, завершить, увидеть
в Журнале и прочитать базовый прогресс; повторять после перезагрузки/повторного онбординга. Платные программы
по-прежнему требуют подписки (tests/test_web/test_v2_subscription_gate.py — синтетическая premium-программа).

Программа — настоящая системная (найдена seed_catalog по натуральному ключу, как в окружениях после миграций),
её access_level = free выставлен миграцией c3f7a9e2d5b1, не тестом."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import SubscriptionStatus, User
from app.db.models_program import Program, ProgramInclusion, TrainingSession
from app.db.repositories.users import UserRepository
from app.domain.program_access import ProgramAccessLevel
from app.services.subscription import SubscriptionService
from scripts.backfill_multi_program import seed_catalog
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_live_session import _make_step_program

LIVE = "/api/v2/sessions/live"


async def _expire(session, user: User) -> None:
    await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.EXPIRED, expires_at=datetime.now(UTC) - timedelta(days=1),
    )


async def _free_program(session) -> Program:
    catalog = await seed_catalog(session)
    program = await session.get(Program, catalog.program_id)
    assert program.access_level == ProgramAccessLevel.FREE.value
    return program


async def _add_to_plan(session, user: User, program_id: int) -> dict:
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions", payload={"program_id": program_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _current_course_items(session, user: User, inclusion_id: int) -> list[int]:
    plan = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")).json()["plan"]
    return [
        item["id"] for item in plan["plan_items"]
        if item["program_inclusion_id"] == inclusion_id and item["plan_week_id"] == plan["current_week_id"]
    ]


async def _run_workout(session, user: User, inclusion: dict, plan_item_ids: list[int]) -> int:
    roles = {e["role"]: e["exercise_id"] for e in inclusion["snapshot"]["exercises"]}
    start = await v2_post(
        session, telegram_id=user.telegram_id, path=LIVE,
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": plan_item_ids},
    )
    assert start.status_code == 200, start.text
    session_id = start.json()["id"]
    sets = [{"exercise_id": roles["block_a"], "value": "11"}] * 3 + [{"exercise_id": roles["block_b"], "value": "4"}] * 4
    batch = await v2_post(
        session, telegram_id=user.telegram_id, path=f"{LIVE}/{session_id}/sets:batch",
        payload={"sets": [{"set_index": i, **s} for i, s in enumerate(sets)]},
    )
    assert batch.status_code == 200, batch.text
    complete = await v2_post(
        session, telegram_id=user.telegram_id, path=f"{LIVE}/{session_id}/complete", payload={"abandoned": False},
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "completed"
    return session_id


async def test_expired_user_trains_the_free_pullups_program_end_to_end(session, user: User):
    await _expire(session, user)
    assert SubscriptionService.is_entitled(user, now=datetime.now(UTC)) is False
    program = await _free_program(session)

    # 8. открыть: каталог и Program Detail (структура) — с явной пометкой free
    programs = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/programs")).json()["programs"]
    assert {"id": program.id, "access_level": "free"}.items() <= next(p for p in programs if p["id"] == program.id).items()
    schedule = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/programs/{program.id}/schedule")
    assert schedule.status_code == 200

    # 9. добавить в план
    inclusion = await _add_to_plan(session, user, program.id)
    assert inclusion["access_level"] == "free"

    # 10. тренировки недели материализованы
    item_ids = await _current_course_items(session, user, inclusion["id"])
    assert len(item_ids) >= 2

    # 11–12. стартовать и завершить — сессия сохранена завершённой
    session_id = await _run_workout(session, user, inclusion, item_ids)
    stored = await session.get(TrainingSession, session_id)
    await session.refresh(stored)
    assert stored.completed_at is not None

    # 13. Журнал показывает эту сессию
    journal = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")).json()
    assert session_id in [s["id"] for s in journal["sessions"]]

    # 14. базовый прогресс программы читается: прогрессия инклюзии сдвинулась, статус Dashboard и аналитика доступны
    stored_inclusion = await session.get(ProgramInclusion, inclusion["id"])
    await session.refresh(stored_inclusion)
    assert stored_inclusion.progression_state != inclusion["progression_state"]
    dashboard = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert dashboard.status_code == 200 and dashboard.json()["status"] != "not_migrated"
    analytics = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/analytics/training")
    assert analytics.status_code == 200


async def test_free_program_session_record_is_not_gated_for_expired_user(session, user: User):
    """Тот же единый путь у POST /api/v2/sessions (source=plan + program_inclusion_id): не 402 для бесплатной."""
    await _expire(session, user)
    inclusion = await _add_to_plan(session, user, (await _free_program(session)).id)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "program_inclusion_id": inclusion["id"], "performed_at": datetime.now(UTC).isoformat(),
            "blocks": [],
        },
    )
    assert response.status_code != 402, response.text


async def test_premium_program_still_rejects_expired_user_while_free_one_works(session, user: User):
    """15: Premium-программа по-прежнему 402 для истёкшего; смешанный запрос с платной строкой — 402 целиком."""
    await _expire(session, user)
    free_inclusion = await _add_to_plan(session, user, (await _free_program(session)).id)
    premium_program = await _make_step_program(session)
    assert premium_program.access_level == ProgramAccessLevel.PREMIUM.value  # по умолчанию — premium
    premium_inclusion = await _add_to_plan(session, user, premium_program.id)
    assert premium_inclusion["access_level"] == "premium"
    free_items = await _current_course_items(session, user, free_inclusion["id"])

    from app.db.models_program import PlanItem
    from app.db.repositories.training_plans import TrainingPlanRepository

    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    premium_item = PlanItem(
        training_plan_id=plan.id, exercise_id=premium_inclusion["snapshot"]["exercises"][0]["exercise_id"],
        count_per_week=3, program_inclusion_id=premium_inclusion["id"],
    )
    session.add(premium_item)
    await session.flush()

    async def start(ids: list[int]):
        return await v2_post(
            session, telegram_id=user.telegram_id, path=LIVE,
            payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": ids},
        )

    premium = await start([premium_item.id])
    assert premium.status_code == 402 and premium.json()["detail"]["code"] == "subscription_required"
    mixed = await start([*free_items, premium_item.id])
    assert mixed.status_code == 402
    assert (await start(free_items)).status_code == 200


async def test_free_access_survives_reload_reonboarding_and_expiry_again(session, user: User):
    """16: доступ к бесплатной программе не зависит от состояния подписки — ни после «перезагрузки» (новые
    запросы), ни после повторного онбординга (триал), ни после его истечения; повтор программы работает."""
    program = await _free_program(session)
    await _expire(session, user)
    inclusion = await _add_to_plan(session, user, program.id)
    first = await _run_workout(session, user, inclusion, await _current_course_items(session, user, inclusion["id"]))

    # повторный онбординг даёт триал, затем он снова истекает
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    await _expire(session, user)

    inclusion = next(  # «перезагрузка»: состояние читается заново с сервера
        i for i in (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")).json()["plan"][
            "program_inclusions"
        ] if i["id"] == inclusion["id"]
    )
    second = await _run_workout(session, user, inclusion, await _current_course_items(session, user, inclusion["id"]))
    assert second != first
    journal = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")).json()
    assert {first, second} <= {s["id"] for s in journal["sessions"]}


async def test_free_flag_is_a_program_property_not_an_endless_subscription(session, user: User):
    """Бесплатность моделируется на программе: пользователь не становится Premium, срок подписки не трогается."""
    await _expire(session, user)
    inclusion = await _add_to_plan(session, user, (await _free_program(session)).id)
    await _run_workout(session, user, inclusion, await _current_course_items(session, user, inclusion["id"]))

    refreshed = await UserRepository(session).get_by_id(user.id)
    await session.refresh(refreshed)
    assert SubscriptionService.is_entitled(refreshed, now=datetime.now(UTC)) is False
    assert refreshed.subscription_expires_at < datetime.now(UTC)
    free_programs = (await session.execute(select(Program).where(Program.access_level == "free"))).scalars().all()
    assert len(free_programs) == 1
