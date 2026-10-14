"""Схемы входов программы «Подтягивания» V5.6 (issue #305) — общие для подключения курса
(POST /program-inclusions) и PUT /program-inclusions/{id}/course/inputs."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.pullups_v5 import AssistanceSetup, EntryInputs


class AssistanceSetupSchema(BaseModel):
    """Однозначная запись помощи: kind = band | bodyweight; для резины — id из личного списка и/или
    название, цвет, крепление, положение стопы/колена (§8.2). Килограммов у резины нет."""

    kind: Literal["band", "bodyweight"]
    equipment_item_id: int | None = None
    name: str | None = Field(default=None, max_length=100)
    colour: str | None = Field(default=None, max_length=50)
    attachment: str | None = Field(default=None, max_length=100)
    body_position: str | None = Field(default=None, max_length=100)

    def to_domain(self) -> AssistanceSetup:
        return AssistanceSetup(**self.model_dump())


class AssistanceConfirmationSchema(BaseModel):
    """Подтверждение ПОЛНОЙ записи помощи блока, ждущего смены (или исправление записи): резина —
    модель/название, цвет, крепление, положение стопы/колена; либо «без помощи». Неполная запись — 422."""

    block: Literal["volume_a", "volume_b", "strength_a", "strength_b"]
    setup: AssistanceSetupSchema


class CourseInputsRequest(BaseModel):
    fresh_max: int | None = Field(default=None, ge=0, le=999)
    volume_capacity: int | None = Field(default=None, ge=1, le=999)
    body_mass_kg: Decimal | None = Field(default=None, gt=0, le=400)
    load_step_kg: Decimal | None = Field(default=None, gt=0, le=20)
    known_a_targets: list[int] | None = Field(default=None, min_length=4, max_length=4)
    known_volume: int | None = Field(default=None, ge=1, le=2000)
    # Недавние 5×5 / 5×3 — со слов пользователя (self-report): сервер их с сохранёнными сессиями не сверяет.
    known_strength_a_kg: Decimal | None = Field(default=None, ge=0, le=300)
    known_strength_b_kg: Decimal | None = Field(default=None, ge=0, le=300)
    volume_assistance: AssistanceSetupSchema | None = None
    strength_assistance: AssistanceSetupSchema | None = None
    assistance_confirmations: list[AssistanceConfirmationSchema] = Field(default_factory=list, max_length=4)
    # §9: пользователь проверил восстановление и внешнюю тяговую нагрузку — прибавки снова назначаются.
    clear_recovery_check: bool = False

    @model_validator(mode="before")
    @classmethod
    def _no_direct_e1rm(cls, data):
        # E1RM — только результат стандартизированного теста (POST …/course/one-rep-max, лестница §10).
        # Прямое значение явно отклоняется (422), а не молча игнорируется.
        if isinstance(data, dict) and data.get("e1rm_kg") is not None:
            raise ValueError("e1rm_kg is set only by the standardized 1RM test (POST …/course/one-rep-max)")
        return data

    def to_domain(self) -> EntryInputs:
        return EntryInputs(
            fresh_max=self.fresh_max, volume_capacity=self.volume_capacity, body_mass_kg=self.body_mass_kg,
            load_step_kg=self.load_step_kg,
            known_a_targets=tuple(self.known_a_targets) if self.known_a_targets is not None else None,
            known_volume=self.known_volume, known_strength_a_kg=self.known_strength_a_kg,
            known_strength_b_kg=self.known_strength_b_kg,
            volume_assistance=self.volume_assistance.to_domain() if self.volume_assistance else None,
            strength_assistance=self.strength_assistance.to_domain() if self.strength_assistance else None,
        )
