"""app.domain.workout_protocol — ExecutionProtocol v1, definition и resolved
типы (Phase A1, issue #213). Тесты на validation каждого правила + главный
инвариант: resolved-типы структурно не содержат prescription/source (это
невозможно выразить в самом типе, не просто соглашение)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.domain.workout_protocol import (
    DefinitionProtocol,
    Interval,
    ProgressionRepsSets,
    ProgressionTimeSets,
    ResolvedInterval,
    ResolvedMaxEffort,
    ResolvedRepsSets,
    ResolvedTimeSets,
    StaticMaxEffort,
    StaticRepsSets,
    StaticTimeSets,
)

# ============================================================================
# StaticRepsSets validation
# ============================================================================


def test_static_reps_sets_valid():
    """StaticRepsSets: sets >= 1, reps >= 1, rest_seconds >= 0."""
    protocol = StaticRepsSets.model_validate({
        "type": "reps_sets",
        "prescription": {"source": "static", "sets": 3, "reps": 15},
        "rest_seconds": 90,
    })

    assert protocol.prescription.sets == 3
    assert protocol.prescription.reps == 15
    assert protocol.rest_seconds == 90


def test_static_reps_sets_rejects_zero_sets():
    """sets=0 должно быть отклонено (ge=1)."""
    with pytest.raises(ValidationError) as exc_info:
        StaticRepsSets.model_validate({
            "type": "reps_sets",
            "prescription": {"source": "static", "sets": 0, "reps": 15},
            "rest_seconds": 90,
        })
    assert "sets" in str(exc_info.value).lower()


def test_static_reps_sets_rejects_zero_reps():
    """reps=0 должно быть отклонено (ge=1)."""
    with pytest.raises(ValidationError) as exc_info:
        StaticRepsSets.model_validate({
            "type": "reps_sets",
            "prescription": {"source": "static", "sets": 3, "reps": 0},
            "rest_seconds": 90,
        })
    assert "reps" in str(exc_info.value).lower()


def test_static_reps_sets_rejects_negative_rest_seconds():
    """rest_seconds < 0 должно быть отклонено (ge=0)."""
    with pytest.raises(ValidationError) as exc_info:
        StaticRepsSets.model_validate({
            "type": "reps_sets",
            "prescription": {"source": "static", "sets": 3, "reps": 15},
            "rest_seconds": -1,
        })
    assert "rest_seconds" in str(exc_info.value).lower()


def test_static_reps_sets_accepts_zero_rest_seconds():
    """rest_seconds=0 валидно (ge=0, не gt=0)."""
    protocol = StaticRepsSets.model_validate({
        "type": "reps_sets",
        "prescription": {"source": "static", "sets": 3, "reps": 15},
        "rest_seconds": 0,
    })

    assert protocol.rest_seconds == 0


# ============================================================================
# ProgressionRepsSets validation
# ============================================================================


def test_progression_reps_sets_valid():
    """ProgressionRepsSets: prescription.source=progression, БЕЗ конкретных
    sets/reps (их нет в этой ветке union вовсе)."""
    protocol = ProgressionRepsSets.model_validate({
        "type": "reps_sets",
        "prescription": {"source": "progression"},
        "rest_seconds": 90,
    })

    assert protocol.prescription.source == "progression"
    assert protocol.rest_seconds == 90
    # Поля sets/reps НЕ существуют в ProgressionRepsPrescription.
    assert not hasattr(protocol.prescription, "sets")
    assert not hasattr(protocol.prescription, "reps")


def test_progression_reps_sets_rejects_negative_rest_seconds():
    """rest_seconds < 0 должно быть отклонено, даже для progression-ветки."""
    with pytest.raises(ValidationError) as exc_info:
        ProgressionRepsSets.model_validate({
            "type": "reps_sets",
            "prescription": {"source": "progression"},
            "rest_seconds": -1,
        })
    assert "rest_seconds" in str(exc_info.value).lower()


# ============================================================================
# StaticTimeSets validation
# ============================================================================


def test_static_time_sets_valid():
    """StaticTimeSets: sets >= 1, duration_seconds > 0, rest_seconds >= 0."""
    protocol = StaticTimeSets.model_validate({
        "type": "time_sets",
        "prescription": {"source": "static", "sets": 3, "duration_seconds": 30},
        "rest_seconds": 60,
    })

    assert protocol.prescription.sets == 3
    assert protocol.prescription.duration_seconds == 30
    assert protocol.rest_seconds == 60


def test_static_time_sets_rejects_zero_duration_seconds():
    """duration_seconds=0 должно быть отклонено (gt=0, не ge=0)."""
    with pytest.raises(ValidationError) as exc_info:
        StaticTimeSets.model_validate({
            "type": "time_sets",
            "prescription": {"source": "static", "sets": 3, "duration_seconds": 0},
            "rest_seconds": 60,
        })
    assert "duration_seconds" in str(exc_info.value).lower()


def test_static_time_sets_rejects_negative_duration_seconds():
    """duration_seconds < 0 должно быть отклонено."""
    with pytest.raises(ValidationError) as exc_info:
        StaticTimeSets.model_validate({
            "type": "time_sets",
            "prescription": {"source": "static", "sets": 3, "duration_seconds": -10},
            "rest_seconds": 60,
        })
    assert "duration_seconds" in str(exc_info.value).lower()


def test_static_time_sets_rejects_zero_sets():
    """sets=0 должно быть отклонено."""
    with pytest.raises(ValidationError) as exc_info:
        StaticTimeSets.model_validate({
            "type": "time_sets",
            "prescription": {"source": "static", "sets": 0, "duration_seconds": 30},
            "rest_seconds": 60,
        })
    assert "sets" in str(exc_info.value).lower()


# ============================================================================
# ProgressionTimeSets validation
# ============================================================================


def test_progression_time_sets_valid():
    """ProgressionTimeSets: схема допускает, хотя не используется в Phase A1."""
    protocol = ProgressionTimeSets.model_validate({
        "type": "time_sets",
        "prescription": {"source": "progression"},
        "rest_seconds": 60,
    })

    assert protocol.prescription.source == "progression"
    assert not hasattr(protocol.prescription, "sets")
    assert not hasattr(protocol.prescription, "duration_seconds")


# ============================================================================
# StaticMaxEffort validation
# ============================================================================


def test_static_max_effort_valid():
    """StaticMaxEffort: attempts >= 1."""
    protocol = StaticMaxEffort.model_validate({
        "type": "max_effort",
        "prescription": {"source": "static", "attempts": 1},
    })

    assert protocol.prescription.attempts == 1


def test_static_max_effort_rejects_zero_attempts():
    """attempts=0 должно быть отклонено (ge=1)."""
    with pytest.raises(ValidationError) as exc_info:
        StaticMaxEffort.model_validate({
            "type": "max_effort",
            "prescription": {"source": "static", "attempts": 0},
        })
    assert "attempts" in str(exc_info.value).lower()


def test_static_max_effort_accepts_multiple_attempts():
    """attempts > 1 валидно (например, 3 попытки на максимум)."""
    protocol = StaticMaxEffort.model_validate({
        "type": "max_effort",
        "prescription": {"source": "static", "attempts": 3},
    })

    assert protocol.prescription.attempts == 3


def test_static_max_effort_with_rest_seconds_valid():
    """Phase C4b-1.5 (issue #188) — rest_seconds явно передан, валиден."""
    protocol = StaticMaxEffort.model_validate({
        "type": "max_effort",
        "prescription": {"source": "static", "attempts": 3},
        "rest_seconds": 180,
    })

    assert protocol.rest_seconds == 180


def test_static_max_effort_rest_seconds_zero_valid():
    protocol = StaticMaxEffort.model_validate({
        "type": "max_effort",
        "prescription": {"source": "static", "attempts": 1},
        "rest_seconds": 0,
    })

    assert protocol.rest_seconds == 0


def test_static_max_effort_negative_rest_seconds_rejected():
    with pytest.raises(ValidationError) as exc_info:
        StaticMaxEffort.model_validate({
            "type": "max_effort",
            "prescription": {"source": "static", "attempts": 1},
            "rest_seconds": -1,
        })
    assert "rest_seconds" in str(exc_info.value).lower()


def test_static_max_effort_backward_compatible_without_rest_seconds():
    """Старый max_effort JSON (созданный до Phase C4b-1.5) без rest_seconds
    вообще — по-прежнему валиден, default=0."""
    protocol = StaticMaxEffort.model_validate({
        "type": "max_effort",
        "prescription": {"source": "static", "attempts": 2},
    })

    assert protocol.rest_seconds == 0


def test_resolved_max_effort_requires_rest_seconds():
    """ResolvedMaxEffort — rest_seconds обязателен на resolved-стороне (не
    backward-compat случай — снимки строятся заново каждый раз builder'ом,
    не читаются напрямую из старого JSON)."""
    resolved = ResolvedMaxEffort(attempts=[{"is_max": True}], rest_seconds=180)
    assert resolved.rest_seconds == 180

    with pytest.raises(ValidationError):
        ResolvedMaxEffort(attempts=[{"is_max": True}])


# ============================================================================
# Interval validation
# ============================================================================


def test_interval_valid():
    """Interval: total_duration_seconds > 0, work_seconds > 0, rest_seconds >= 0,
    work_seconds + rest_seconds <= total_duration_seconds, starts_with="work"."""
    protocol = Interval.model_validate({
        "type": "interval",
        "total_duration_seconds": 180,
        "work_seconds": 10,
        "rest_seconds": 20,
        "starts_with": "work",
    })

    assert protocol.total_duration_seconds == 180
    assert protocol.work_seconds == 10
    assert protocol.rest_seconds == 20
    assert protocol.starts_with == "work"


def test_interval_rejects_zero_total_duration_seconds():
    """total_duration_seconds=0 должно быть отклонено (gt=0)."""
    with pytest.raises(ValidationError) as exc_info:
        Interval.model_validate({
            "type": "interval",
            "total_duration_seconds": 0,
            "work_seconds": 10,
            "rest_seconds": 20,
            "starts_with": "work",
        })
    assert "total_duration_seconds" in str(exc_info.value).lower()


def test_interval_rejects_zero_work_seconds():
    """work_seconds=0 должно быть отклонено (gt=0)."""
    with pytest.raises(ValidationError) as exc_info:
        Interval.model_validate({
            "type": "interval",
            "total_duration_seconds": 180,
            "work_seconds": 0,
            "rest_seconds": 20,
            "starts_with": "work",
        })
    assert "work_seconds" in str(exc_info.value).lower()


def test_interval_rejects_negative_rest_seconds():
    """rest_seconds < 0 должно быть отклонено."""
    with pytest.raises(ValidationError) as exc_info:
        Interval.model_validate({
            "type": "interval",
            "total_duration_seconds": 180,
            "work_seconds": 10,
            "rest_seconds": -5,
            "starts_with": "work",
        })
    assert "rest_seconds" in str(exc_info.value).lower()


def test_interval_accepts_zero_rest_seconds():
    """rest_seconds=0 валидно (ge=0, не gt=0) — интервал без отдыха."""
    protocol = Interval.model_validate({
        "type": "interval",
        "total_duration_seconds": 180,
        "work_seconds": 10,
        "rest_seconds": 0,
        "starts_with": "work",
    })

    assert protocol.rest_seconds == 0


def test_interval_rejects_work_plus_rest_exceeds_total():
    """work_seconds + rest_seconds > total_duration_seconds должно быть
    отклонено — один цикл не влезает в общую длительность."""
    with pytest.raises(ValidationError) as exc_info:
        Interval.model_validate({
            "type": "interval",
            "total_duration_seconds": 180,
            "work_seconds": 100,
            "rest_seconds": 100,
            "starts_with": "work",
        })
    # model_validator бросает ValueError с кастомным сообщением.
    assert "превышает total_duration_seconds" in str(exc_info.value)


def test_interval_accepts_work_plus_rest_equal_to_total():
    """work_seconds + rest_seconds = total_duration_seconds валидно —
    граничный случай (ровно один цикл, без "довеска" времени)."""
    protocol = Interval.model_validate({
        "type": "interval",
        "total_duration_seconds": 30,
        "work_seconds": 10,
        "rest_seconds": 20,
        "starts_with": "work",
    })

    assert protocol.work_seconds + protocol.rest_seconds == protocol.total_duration_seconds


def test_interval_rejects_starts_with_rest():
    """starts_with="rest" должно быть отклонено в Phase A1 (только "work")."""
    with pytest.raises(ValidationError) as exc_info:
        Interval.model_validate({
            "type": "interval",
            "total_duration_seconds": 180,
            "work_seconds": 10,
            "rest_seconds": 20,
            "starts_with": "rest",
        })
    assert "starts_with" in str(exc_info.value).lower()


# ============================================================================
# Resolved types — main invariant: no prescription/source fields
# ============================================================================


def test_resolved_reps_sets_has_no_prescription_field():
    """ResolvedRepsSets структурно НЕ содержит поля prescription — это
    отдельная модель, а не StaticRepsSets/ProgressionRepsSets с опциональным
    prescription=None."""
    protocol = ResolvedRepsSets.model_validate({
        "type": "reps_sets",
        "sets": [{"target_reps": 10}, {"target_reps": 10}, {"target_reps": 10}],
        "rest_seconds": 90,
    })

    assert not hasattr(protocol, "prescription")
    assert protocol.sets[0].target_reps == 10
    assert len(protocol.sets) == 3


def test_resolved_reps_sets_rejects_empty_sets():
    """sets не может быть пустым массивом (min_length=1)."""
    with pytest.raises(ValidationError) as exc_info:
        ResolvedRepsSets.model_validate({
            "type": "reps_sets",
            "sets": [],
            "rest_seconds": 90,
        })
    assert "sets" in str(exc_info.value).lower()


def test_resolved_time_sets_has_no_prescription_field():
    """ResolvedTimeSets структурно НЕ содержит поля prescription."""
    protocol = ResolvedTimeSets.model_validate({
        "type": "time_sets",
        "sets": [{"target_seconds": 30}, {"target_seconds": 30}, {"target_seconds": 30}],
        "rest_seconds": 60,
    })

    assert not hasattr(protocol, "prescription")
    assert protocol.sets[0].target_seconds == 30
    assert len(protocol.sets) == 3


def test_resolved_time_sets_rejects_zero_target_seconds():
    """target_seconds=0 должно быть отклонено (gt=0)."""
    with pytest.raises(ValidationError) as exc_info:
        ResolvedTimeSets.model_validate({
            "type": "time_sets",
            "sets": [{"target_seconds": 0}],
            "rest_seconds": 60,
        })
    assert "target_seconds" in str(exc_info.value).lower()


def test_resolved_max_effort_has_no_prescription_field():
    """ResolvedMaxEffort структурно НЕ содержит поля prescription."""
    protocol = ResolvedMaxEffort.model_validate({
        "type": "max_effort",
        "attempts": [{"is_max": True}],
        "rest_seconds": 0,
    })

    assert not hasattr(protocol, "prescription")
    assert protocol.attempts[0].is_max is True


def test_resolved_max_effort_rejects_empty_attempts():
    """attempts не может быть пустым массивом (min_length=1)."""
    with pytest.raises(ValidationError) as exc_info:
        ResolvedMaxEffort.model_validate({
            "type": "max_effort",
            "attempts": [],
        })
    assert "attempts" in str(exc_info.value).lower()


def test_resolved_interval_has_no_prescription_field():
    """ResolvedInterval структурно НЕ содержит поля prescription — у Interval
    его никогда не было (нет progression-формы для interval), но инвариант
    "resolved-типы не содержат prescription/source" касается всех resolved-типов,
    включая Interval (просто у него этот инвариант тривиально выполнен)."""
    protocol = ResolvedInterval.model_validate({
        "type": "interval",
        "total_duration_seconds": 180,
        "work_seconds": 10,
        "rest_seconds": 20,
        "starts_with": "work",
    })

    assert not hasattr(protocol, "prescription")
    assert not hasattr(protocol, "source")


def test_resolved_interval_validates_work_plus_rest_like_definition():
    """ResolvedInterval применяет ту же валидацию work_seconds + rest_seconds
    <= total_duration_seconds, что и definition Interval."""
    with pytest.raises(ValidationError) as exc_info:
        ResolvedInterval.model_validate({
            "type": "interval",
            "total_duration_seconds": 180,
            "work_seconds": 100,
            "rest_seconds": 100,
            "starts_with": "work",
        })
    assert "превышает total_duration_seconds" in str(exc_info.value)


# ============================================================================
# Structural proof: cannot pass prescription/source to resolved types
# ============================================================================


def test_resolved_reps_sets_rejects_prescription_field_structurally():
    """Попытка передать prescription в ResolvedRepsSets должна быть отклонена
    Pydantic (это не поле модели вообще, не просто nullable)."""
    with pytest.raises(ValidationError):
        ResolvedRepsSets.model_validate({
            "type": "reps_sets",
            "sets": [{"target_reps": 10}],
            "rest_seconds": 90,
            "prescription": {"source": "static", "sets": 3, "reps": 10},  # лишнее поле
        })


def test_resolved_time_sets_rejects_prescription_field_structurally():
    """Попытка передать prescription в ResolvedTimeSets должна быть отклонена."""
    with pytest.raises(ValidationError):
        ResolvedTimeSets.model_validate({
            "type": "time_sets",
            "sets": [{"target_seconds": 30}],
            "rest_seconds": 60,
            "prescription": {"source": "static", "sets": 3, "duration_seconds": 30},
        })


def test_resolved_max_effort_rejects_prescription_field_structurally():
    """Попытка передать prescription в ResolvedMaxEffort должна быть отклонена."""
    with pytest.raises(ValidationError):
        ResolvedMaxEffort.model_validate({
            "type": "max_effort",
            "attempts": [{"is_max": True}],
            "prescription": {"source": "static", "attempts": 1},
        })


# ============================================================================
# DefinitionProtocol — discriminated union regression (issue #215, gate 5)
#
# Найденный при интеграции Phase B1 баг: изначальный
# Field(discriminator="type") был структурно сломан для reps_sets/
# time_sets — StaticRepsSets и ProgressionRepsSets несут одно и то же
# значение type="reps_sets", различаясь только вложенным
# prescription.source; Pydantic требует уникального значения дискриминатора
# на вариант union, а не два класса на одно значение. Ни один из тестов
# выше не находил эту ошибку, потому что каждый класс проверялся отдельно
# (StaticRepsSets.model_validate(...) и т.д.) — сама сборка
# TypeAdapter(DefinitionProtocol) не вызывалась НИ РАЗУ до этого момента.
# Эти тесты специально конструируют union целиком и парсят через него.
# ============================================================================

_definition_adapter = TypeAdapter(DefinitionProtocol)


def test_definition_protocol_union_constructs_without_error():
    """Сама сборка TypeAdapter(DefinitionProtocol) не должна падать —
    именно это упало в исходном баге (TypeError на конструирование схемы,
    ещё до какого-либо .validate_python() вызова)."""
    assert _definition_adapter is not None


def test_definition_protocol_parses_static_reps_sets():
    result = _definition_adapter.validate_python({
        "type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 15}, "rest_seconds": 90,
    })
    assert isinstance(result, StaticRepsSets)
    assert result.prescription.sets == 3
    assert result.prescription.reps == 15


def test_definition_protocol_parses_progression_reps_sets():
    result = _definition_adapter.validate_python({
        "type": "reps_sets", "prescription": {"source": "progression"}, "rest_seconds": 90,
    })
    assert isinstance(result, ProgressionRepsSets)


def test_definition_protocol_parses_static_time_sets():
    result = _definition_adapter.validate_python({
        "type": "time_sets", "prescription": {"source": "static", "sets": 3, "duration_seconds": 30}, "rest_seconds": 60,
    })
    assert isinstance(result, StaticTimeSets)
    assert result.prescription.duration_seconds == 30


def test_definition_protocol_parses_progression_time_sets():
    result = _definition_adapter.validate_python({
        "type": "time_sets", "prescription": {"source": "progression"}, "rest_seconds": 60,
    })
    assert isinstance(result, ProgressionTimeSets)


def test_definition_protocol_parses_max_effort():
    result = _definition_adapter.validate_python({
        "type": "max_effort", "prescription": {"source": "static", "attempts": 1},
    })
    assert isinstance(result, StaticMaxEffort)
    assert result.prescription.attempts == 1


def test_definition_protocol_parses_interval():
    result = _definition_adapter.validate_python({
        "type": "interval", "total_duration_seconds": 180, "work_seconds": 10, "rest_seconds": 20, "starts_with": "work",
    })
    assert isinstance(result, Interval)
    assert result.total_duration_seconds == 180


def test_definition_protocol_rejects_unknown_type():
    with pytest.raises(ValidationError):
        _definition_adapter.validate_python({"type": "amrap", "rest_seconds": 90})


def test_definition_protocol_rejects_reps_sets_without_prescription_source():
    """Ambiguous payload — type=reps_sets, но prescription.source отсутствует
    вовсе (не static, не progression) — должен быть отклонён, не тихо
    выбрать первый попавшийся вариант union."""
    with pytest.raises(ValidationError):
        _definition_adapter.validate_python({
            "type": "reps_sets", "prescription": {"sets": 3, "reps": 15}, "rest_seconds": 90,
        })
