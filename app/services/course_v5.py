"""Оркестрация программы «Подтягивания» V5.6 (issue #305) поверх чистого домена app.domain.pullups_v5.

* ``prescribe_main`` — рецепт следующего основного занятия (A или B) при живом старте. Нет нужных
  входов — ``CourseSetupRequiredError`` (роут → 409 ``course_setup_required``): ничего не угадывается.
* ``targets_for`` — SetTarget блоков занятия: объём (упражнение роли ``block_a`` снимка инклюзии) и сила
  (упражнение роли ``block_b``). Полный рецепт (роль A/B, уровень, отдых 240/30/900/180, маркеры AMRAP /
  контрольного подхода / стоп-правила B, помощь, вес, входы расчёта) пишется ОДИН раз в снимок сессии
  (``prescription_snapshot.provenance.course_program``, WORKOUT_DOMAIN_V2 S1) — его исполняет движок
  #306 и его же читает прогрессия при завершении.
* ``advance_from_session`` — шаг прогрессии по завершённому занятию: вход — рецепт ИЗ СНИМКА сессии и её
  факт. Только вперёд: прошлые сессии, их снимки и PlanItem не пересчитываются; правка истории (#307)
  меняет факт, но не состояние.
* ``update_inputs`` / ``record_one_rep_max`` — ввод недостающих входов (R, резины, шаг веса, выбор
  следующей резины, снятие паузы §9) и запись теста 1RM — только вперёд. E1RM приходит ТОЛЬКО из
  оконченного теста по лестнице §10, проверенного сервером; общий ввод его не принимает.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import ProgramInclusion
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.training_sessions import SessionBlockDetail, SessionDetail, SetTargetInput
from app.domain.multi_program import MetricType
from app.domain.pullups_v5 import (
    BAND_KIND,
    PROGRAM_VERSION,
    AssistanceSetup,
    BlockResult,
    EntryInputs,
    OneRmAttempt,
    OneRmResult,
    PrescriptionPending,
    SessionPrescription,
    SessionResult,
    SetMarker,
    V5State,
    advance_session,
    apply_inputs,
    clear_recovery_check,
    confirm_assistance,
    is_v5_state,
    one_rm_rest_ok,
    pending_inputs,
    prescribe_session,
    record_one_rm_test,
)
from app.domain.training_session_v2 import SetStatus

COURSE_PROGRAM_KEY = "course_program"
VOLUME_ROLE, STRENGTH_ROLE = "block_a", "block_b"


class CourseSetupRequiredError(Exception):
    """Рецепт основного занятия V5.6 не считается без входов — роут → 409 {code: course_setup_required}."""

    def __init__(self, inclusion_id: int, missing: tuple[str, ...]) -> None:
        super().__init__(f"course_setup_required: inclusion={inclusion_id} missing={missing}")
        self.inclusion_id = inclusion_id
        self.missing = missing


class OneRepMaxTooSoonError(Exception):
    """Тест 1RM раньше 48 ч после тяжёлой тяговой работы (§8.3)."""


@dataclass(frozen=True)
class CourseAdvanceResult:
    progression: dict | None
    skipped_reason: str | None


def v5_state(inclusion: ProgramInclusion) -> V5State:
    return V5State.from_dict(inclusion.progression_state)


async def assistance_ladder(session: AsyncSession, user_id: int) -> tuple[AssistanceSetup, ...]:
    """Личный упорядоченный список резин (EquipmentItem.position: 0 — больше всего помощи) — единственный
    источник «следующей ступени» помощи. Пустой список — следующую резину выбирает пользователь."""
    items = await EquipmentItemRepository(session).list_for_user(user_id)
    return tuple(AssistanceSetup(kind=BAND_KIND, equipment_item_id=item.id, name=item.name) for item in items)


def _store(inclusion: ProgramInclusion, state: V5State) -> None:
    # Новый dict целиком — SQLAlchemy надёжно видит только замену JSONB-атрибута.
    inclusion.progression_state = state.to_dict()


async def prescribe_main(
    session: AsyncSession, inclusion: ProgramInclusion, *, body_mass_kg: Decimal | None,
) -> SessionPrescription:
    """Рецепт следующего основного занятия. Текущая масса тела из профиля (обновляется раз в неделю,
    §8.5) переносится во входы ВПЕРЁД — для будущих расчётов; выданные рецепты не трогаются."""
    state = v5_state(inclusion)
    if body_mass_kg is not None and state.inputs.body_mass_kg != body_mass_kg:
        state = apply_inputs(state, EntryInputs(body_mass_kg=body_mass_kg))
        _store(inclusion, state)
        await session.flush()
    prescription = prescribe_session(state)
    if isinstance(prescription, PrescriptionPending):
        raise CourseSetupRequiredError(inclusion.id, tuple(item.value for item in prescription.missing))
    return prescription


def targets_for(prescription: SessionPrescription) -> tuple[list[SetTargetInput], list[SetTargetInput]]:
    """SetTarget объёмного и силового блоков. Технический AMRAP A — ``is_max_set`` с минимальной целью p4
    в ``value`` (подход действительно на максимум; прогрессия читает его по позиции, а не по флагу).
    Контрольный подход 5–8 — обычная цель 5 (потолок 8 — в снимке). Подходы B — по S×q; стоп-правило
    исполняет движок #306 (в снимке), прогрессия применяет его к факту сама."""
    def block_targets(block) -> list[SetTargetInput]:
        return [
            SetTargetInput(
                set_number=s.set_number, metric_type=MetricType.REPS, value=Decimal(s.target_reps), unit="reps",
                is_max_set=s.marker is SetMarker.AMRAP, kind="max_reps" if s.marker is SetMarker.AMRAP else "reps",
            )
            for s in block.sets
        ]
    return block_targets(prescription.volume), block_targets(prescription.strength)


def course_snapshot_patch(snapshot: dict, prescription: dict, *, progression_state_rev: int) -> dict:
    """Дописывает в синтезированный снимок сессии рецепт V5.6: отдых подходов и блоков (240/30 → 900 →
    180) в стандартные поля снимка и полный рецепт в provenance.course_program. Вызывается один раз при
    создании сессии (S1)."""
    blocks = snapshot.get("blocks") or []
    for index, (snap_block, course_block) in enumerate(zip(blocks, prescription["blocks"], strict=False)):
        snap_block["rest_after_block_seconds"] = prescription["inter_block_rest_seconds"] if index == 0 else None
        for snap_set, course_set in zip(snap_block.get("sets") or [], course_block["sets"], strict=False):
            snap_set["rest_after_seconds"] = course_set["rest_after_seconds"]
    provenance = snapshot.setdefault("provenance", {})
    provenance["strategy"] = PROGRAM_VERSION
    provenance["progression_state_rev"] = progression_state_rev
    provenance[COURSE_PROGRAM_KEY] = prescription
    return snapshot


def course_prescription_of(detail: SessionDetail) -> dict | None:
    snapshot = detail.prescription_snapshot or {}
    prescription = (snapshot.get("provenance") or {}).get(COURSE_PROGRAM_KEY)
    return prescription if (prescription or {}).get("program_version") == PROGRAM_VERSION else None


def _block_result(block: SessionBlockDetail, planned: int) -> BlockResult:
    """Факт ПЛАНОВЫХ подходов по порядку (подходы «+ Ещё» — не план, §8.5: лишнее не ускоряет);
    невыполненный подход (#307 not_performed) — None."""
    logs = sorted((log for log in block.set_logs if not log.is_extra), key=lambda log: log.set_number)
    reps: list[int | None] = [
        int(log.value) if log.status == SetStatus.PERFORMED.value else None for log in logs[:planned]
    ]
    reps += [None] * (planned - len(reps))
    return BlockResult(reps=tuple(reps), technique_valid=block.technique_valid, rest_within_limit=block.rest_within_limit)


def session_result(detail: SessionDetail, prescription: dict) -> SessionResult | None:
    if len(detail.blocks) != 2:
        return None
    volume_block, strength_block = sorted(detail.blocks, key=lambda block: block.order_index)
    volume_rx, strength_rx = prescription["blocks"]
    return SessionResult(
        volume=_block_result(volume_block, len(volume_rx["sets"])),
        strength=_block_result(strength_block, len(strength_rx["sets"])),
    )


async def advance_from_session(
    session: AsyncSession, inclusion: ProgramInclusion, detail: SessionDetail, *, user_id: int,
    body_mass_kg: Decimal | None,
) -> CourseAdvanceResult:
    """Прогрессия V5.6 по завершённому основному занятию — рецепт берётся ИЗ СНИМКА этой сессии."""
    prescription = course_prescription_of(detail)
    if prescription is None:
        return CourseAdvanceResult(None, "v5_requires_prescribed_session")
    result = session_result(detail, prescription)
    if result is None:
        return CourseAdvanceResult(None, "blocks_do_not_match_step_roles")
    advance = advance_session(
        v5_state(inclusion), prescription, result, body_mass=body_mass_kg,
        ladder=await assistance_ladder(session, user_id),
    )
    _store(inclusion, advance.state)
    await session.flush()
    progression = {
        "program_version": PROGRAM_VERSION,
        "workout_role": prescription["workout_role"],
        "level_before": prescription["level"],
        "level_after": advance.state.level.value if advance.state.level is not None else None,
        "qualified": advance.qualified,
        "blocks": [advance.volume.to_dict(), advance.strength.to_dict()],
        "next_workout_role": advance.state.next_role.value,
        "pending_inputs": [item.value for item in pending_inputs(advance.state)],
    }
    return CourseAdvanceResult(progression, None)


async def update_inputs(
    session: AsyncSession, inclusion: ProgramInclusion, update: EntryInputs, *, clear_recovery: bool = False,
    confirmations: list[tuple[str, AssistanceSetup]] | None = None,
) -> V5State:
    """Входы и подтверждения помощи — только вперёд. Неполная/недопустимая запись помощи —
    V5StateError (роут → 422), состояние не меняется."""
    state = apply_inputs(v5_state(inclusion), update)
    for block, setup in confirmations or []:
        state = confirm_assistance(state, block, setup)
    if clear_recovery:
        state = clear_recovery_check(state)
    _store(inclusion, state)
    await session.flush()
    return state


async def record_one_rep_max(
    session: AsyncSession, inclusion: ProgramInclusion, attempts: list[OneRmAttempt], *, performed_at: datetime,
    last_heavy_pulling_at: datetime | None,
) -> tuple[V5State, OneRmResult]:
    """Тест 1RM — отдельный свежий день, не раньше 48 ч после тяжёлой тяговой работы (§8.3)."""
    hours = (performed_at - last_heavy_pulling_at).total_seconds() / 3600 if last_heavy_pulling_at is not None else None
    if not one_rm_rest_ok(hours_since_heavy_pulling=hours):
        raise OneRepMaxTooSoonError()
    # Лестница, повторения, скорости, стоп и «тест окончен» проверяются целиком ДО записи: некорректный
    # тест — OneRmTestError, состояние и история тестов не меняются.
    state, result = record_one_rm_test(v5_state(inclusion), attempts, performed_at=performed_at.isoformat())
    _store(inclusion, state)
    await session.flush()
    return state, result


async def inclusion_for_user(session: AsyncSession, inclusion_id: int, user_id: int) -> ProgramInclusion | None:
    inclusion = await TrainingPlanRepository(session).get_inclusion_for_user(inclusion_id, user_id)
    if inclusion is None or not is_v5_state(inclusion.progression_state):
        return None
    return inclusion
