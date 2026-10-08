"""WorkoutDefinition v2 — канонический set-explicit рецепт тренировки (issue #303, Wave 1a).

Контракт: docs/domain/WORKOUT_DOMAIN_V2.md (§3 форма, §3.2 normalize, §4 инварианты W1–W8, §5
версии и PrescriptionSnapshot, §7 describe, §8 V1 → v2). Решения AD-1 (рецепт хранится
списком подходов, `sets × reps` — только сокращение при вводе) и AD-2 (неизменяемые версии с
хешем содержимого) — docs/domain/README.md.

Чистый домен: ни aiogram, ни SQLAlchemy. Типы — frozen-датаклассы, вес — Decimal.

Почему не Pydantic, как app.domain.workout_protocol (V1): нормализация здесь — не только
проверка формы, но и детерминированное заполнение умолчаний (отдых, подготовка, роль подхода)
плюс межполевые инварианты W1–W8 с явными кодами ошибок. Каждая ошибка — WorkoutContentError с
кодом инварианта и путём до поля, чтобы веб-слой отдал 422 с понятной причиной, а не 500 и не
молчаливое «исправление» смысла тренировки.

Продуктовые числа этого модуля (не научные факты, CLAUDE.md):
- SYSTEM_DEFAULT_REST_SECONDS = 90 — тот же DEFAULT_REST_SECONDS, что у живой сессии V1
  (app.domain.live_session); контракт §3.2 называет его явно.
- DEFAULT_PREP_SECONDS = 5 — тот же GET_READY_SECONDS, контракт §3.6.
- MAX_SETS_PER_BLOCK = 100, MAX_TARGET_REPS = 999 (= app.bot.parsing.MAX_REPS: домен не
  импортирует app.bot, поэтому значение повторено и сверяется тестом), MAX_SECONDS = 86400 —
  потолки «явно абсурдного ввода», не тренировочные нормы.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 2
SNAPSHOT_SCHEMA_VERSION = 2

SYSTEM_DEFAULT_REST_SECONDS = 90
DEFAULT_PREP_SECONDS = 5
MAX_SETS_PER_BLOCK = 100
MAX_BLOCKS = 50
MAX_TARGET_REPS = 999
MAX_SECONDS = 86_400
MAX_INTERVAL_ROUNDS = 1_000
MAX_TITLE_LENGTH = 255


class SetKind(StrEnum):
    REPS = "reps"
    MAX_REPS = "max_reps"
    TIME = "time"
    MAX_TIME = "max_time"


class SetRole(StrEnum):
    WORKING = "working"
    MAX = "max"
    WARMUP = "warmup"


class BlockKind(StrEnum):
    SETS = "sets"
    INTERVAL = "interval"


class BlockSource(StrEnum):
    STATIC = "static"
    PROGRESSION = "progression"


class LoadKind(StrEnum):
    BODYWEIGHT = "bodyweight"
    BAND = "band"
    ADDED_KG = "added_kg"
    ASSISTED_KG = "assisted_kg"


class WorkoutContentError(ValueError):
    """Невалидное содержимое: code — инвариант (W1…W8) или вид ошибки формы, path — путь до
    поля («blocks[1].sets[3].target_reps»). Веб-слой превращает в 422."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code} at {path}: {message}")
        self.code = code
        self.path = path
        self.message = message


# ============================================================================
# Типы
# ============================================================================


@dataclass(frozen=True)
class LoadSpec:
    """Нагрузка: собственный вес / резина (item_id — EquipmentItem, может быть неизвестен) /
    отягощение / облегчение в кг. value_kg обязателен и > 0 ровно для *_kg."""

    kind: LoadKind
    value_kg: Decimal | None = None
    item_id: int | None = None


@dataclass(frozen=True)
class SetPrescription:
    """Один элемент = один подход, который выполняет пользователь (контракт §3).

    rest_after_seconds — отдых ПОСЛЕ этого подхода; None ровно у последнего подхода блока (W4).
    0 — «без фазы отдыха», явное значение, не умолчание."""

    kind: SetKind
    target_reps: int | None = None
    target_seconds: int | None = None
    load: LoadSpec | None = None
    rest_after_seconds: int | None = None
    role: SetRole = SetRole.WORKING


@dataclass(frozen=True)
class IntervalSpec:
    work_seconds: int
    rest_seconds: int
    rounds: int
    record_reps_per_round: bool = False


@dataclass(frozen=True)
class Block:
    key: str
    exercise_id: int
    kind: BlockKind
    prep_seconds: int
    rest_after_block_seconds: int | None
    extra_sets_allowed: bool
    load: LoadSpec | None = None
    source: BlockSource = BlockSource.STATIC
    progression_role: str | None = None
    sets: tuple[SetPrescription, ...] = ()
    interval: IntervalSpec | None = None


@dataclass(frozen=True)
class WorkoutContent:
    """Нормализованное содержимое версии (schema_version = 2). Строится только через
    normalize() — прямой конструктор не проверяет инварианты."""

    title: str
    default_rest_seconds: int | None
    blocks: tuple[Block, ...]
    schema_version: int = SCHEMA_VERSION


# ============================================================================
# Разбор/проверка ввода
# ============================================================================

_WORKOUT_KEYS = frozenset({"schema_version", "title", "default_rest_seconds", "blocks"})
_BLOCK_KEYS = frozenset({
    "key", "exercise_id", "kind", "prep_seconds", "rest_after_block_seconds",
    "extra_sets_allowed", "load", "source", "progression_role", "sets", "interval",
    # сокращение «N × R» / «N × S сек» (§3.2 п.1), только для kind=sets, source=static
    "reps", "seconds", "rest_seconds",
})
_SET_KEYS = frozenset({"kind", "target_reps", "target_seconds", "load", "rest_after_seconds", "role"})
_INTERVAL_KEYS = frozenset({"work_seconds", "rest_seconds", "rounds", "record_reps_per_round"})
_LOAD_KEYS = frozenset({"kind", "value_kg", "item_id"})
_MISSING = object()


def _fail(code: str, path: str, message: str) -> WorkoutContentError:
    return WorkoutContentError(code, path, message)


def _require_mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail("invalid_type", path, "ожидается объект")
    return value


def _reject_unknown(raw: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise _fail("unknown_field", f"{path}.{unknown[0]}", f"неизвестное поле {unknown[0]!r}")


def _int(value: object, path: str, *, minimum: int, maximum: int) -> int:
    # bool — подкласс int в Python; True как «1 повторение» — тихая подмена смысла.
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail("invalid_type", path, "ожидается целое число")
    if value < minimum or value > maximum:
        raise _fail("out_of_range", path, f"допустимо {minimum}…{maximum}, получено {value}")
    return value


def _optional_int(value: object, path: str, *, minimum: int, maximum: int) -> int | None:
    if value is None or value is _MISSING:
        return None
    return _int(value, path, minimum=minimum, maximum=maximum)


def _enum(enum_type: type[StrEnum], value: object, path: str) -> Any:
    try:
        return enum_type(value)
    except ValueError:
        allowed = ", ".join(member.value for member in enum_type)
        raise _fail("invalid_value", path, f"допустимо: {allowed}") from None


def _parse_load(raw: object, path: str) -> LoadSpec | None:
    if raw is None:
        return None
    data = _require_mapping(raw, path)
    _reject_unknown(data, _LOAD_KEYS, path)
    kind = _enum(LoadKind, data.get("kind"), f"{path}.kind")
    value_raw = data.get("value_kg")
    item_id = _optional_int(data.get("item_id"), f"{path}.item_id", minimum=1, maximum=2**63 - 1)
    value_kg: Decimal | None = None
    if kind in (LoadKind.ADDED_KG, LoadKind.ASSISTED_KG):
        if value_raw is None or isinstance(value_raw, bool):
            raise _fail("invalid_load", f"{path}.value_kg", "обязателен вес в кг")
        try:
            value_kg = Decimal(str(value_raw))
        except InvalidOperation:
            raise _fail("invalid_load", f"{path}.value_kg", "вес должен быть числом") from None
        if not value_kg.is_finite() or value_kg <= 0 or value_kg > 500:
            raise _fail("invalid_load", f"{path}.value_kg", "вес должен быть > 0 и ≤ 500 кг")
        if item_id is not None:
            raise _fail("invalid_load", f"{path}.item_id", "item_id допустим только для резины")
    else:
        if value_raw is not None:
            raise _fail("invalid_load", f"{path}.value_kg", f"у нагрузки {kind.value} нет веса")
        if kind is LoadKind.BODYWEIGHT and item_id is not None:
            raise _fail("invalid_load", f"{path}.item_id", "item_id допустим только для резины")
    return LoadSpec(kind=kind, value_kg=value_kg, item_id=item_id)


def _parse_set(raw: object, path: str) -> tuple[SetPrescription, object]:
    """Возвращает подход и «сырой» rest_after_seconds (_MISSING/None/int) — умолчание отдыха
    решается на уровне блока, где известно, какой подход последний."""
    data = _require_mapping(raw, path)
    if "is_extra" in data:
        raise _fail("W8", f"{path}.is_extra", "дополнительные подходы не входят в рецепт, только в журнал")
    _reject_unknown(data, _SET_KEYS, path)
    kind = _enum(SetKind, data.get("kind"), f"{path}.kind")
    target_reps_raw = data.get("target_reps")
    target_seconds_raw = data.get("target_seconds")

    target_reps: int | None = None
    target_seconds: int | None = None
    if kind is SetKind.REPS:
        if target_reps_raw is None:
            raise _fail("missing_target", f"{path}.target_reps", "у подхода reps нужна цель")
        target_reps = _int(target_reps_raw, f"{path}.target_reps", minimum=1, maximum=MAX_TARGET_REPS)
        if target_seconds_raw is not None:
            raise _fail("invalid_target", f"{path}.target_seconds", "у подхода reps нет цели по времени")
    elif kind is SetKind.TIME:
        if target_seconds_raw is None:
            raise _fail("missing_target", f"{path}.target_seconds", "у подхода time нужна длительность")
        target_seconds = _int(target_seconds_raw, f"{path}.target_seconds", minimum=1, maximum=MAX_SECONDS)
        if target_reps_raw is not None:
            raise _fail("invalid_target", f"{path}.target_reps", "у подхода time нет цели в повторениях")
    else:
        # W2: «максимум» не имеет цели вообще — ни 0, ни числа.
        if target_reps_raw is not None:
            raise _fail("W2", f"{path}.target_reps", "у подхода на максимум нет цели")
        if target_seconds_raw is not None:
            raise _fail("W2", f"{path}.target_seconds", "у подхода на максимум нет цели")

    default_role = SetRole.MAX if kind in (SetKind.MAX_REPS, SetKind.MAX_TIME) else SetRole.WORKING
    role_raw = data.get("role")
    role = default_role if role_raw is None else _enum(SetRole, role_raw, f"{path}.role")

    rest_raw = data.get("rest_after_seconds", _MISSING)
    if rest_raw is not _MISSING and rest_raw is not None:
        _int(rest_raw, f"{path}.rest_after_seconds", minimum=0, maximum=MAX_SECONDS)
    return (
        SetPrescription(
            kind=kind, target_reps=target_reps, target_seconds=target_seconds,
            load=_parse_load(data.get("load"), f"{path}.load"), role=role,
        ),
        rest_raw,
    )


def _resolve_set_rests(
    parsed: Sequence[tuple[SetPrescription, object]], *, default_rest: int, path: str,
) -> tuple[SetPrescription, ...]:
    """§3.2 п.2 + W4: у не-последнего подхода отдых = свой ?? workout default ?? 90; у
    последнего — None. Явный отдых у последнего подхода отклоняется (W4), а не выбрасывается
    молча: «отдых после блока» задаётся rest_after_block_seconds."""
    resolved: list[SetPrescription] = []
    last = len(parsed) - 1
    for index, (set_, rest_raw) in enumerate(parsed):
        if index == last:
            if rest_raw is not _MISSING and rest_raw is not None:
                raise _fail(
                    "W4", f"{path}[{index}].rest_after_seconds",
                    "у последнего подхода блока нет отдыха (используйте rest_after_block_seconds)",
                )
            rest = None
        else:
            rest = default_rest if rest_raw is _MISSING or rest_raw is None else int(rest_raw)  # type: ignore[call-overload]
        resolved.append(_replace_rest(set_, rest))
    return tuple(resolved)


def _replace_rest(set_: SetPrescription, rest: int | None) -> SetPrescription:
    return SetPrescription(
        kind=set_.kind, target_reps=set_.target_reps, target_seconds=set_.target_seconds,
        load=set_.load, rest_after_seconds=rest, role=set_.role,
    )


def _expand_shorthand(data: Mapping[str, Any], path: str) -> list[dict[str, Any]]:
    """§3.2 п.1: {sets: N, reps: R[, rest_seconds]} / {sets: N, seconds: S[, rest_seconds]} →
    N явных элементов. Ровно одно из reps/seconds."""
    count = _int(data["sets"], f"{path}.sets", minimum=1, maximum=MAX_SETS_PER_BLOCK)
    has_reps = data.get("reps") is not None
    has_seconds = data.get("seconds") is not None
    if has_reps == has_seconds:
        raise _fail("invalid_shorthand", path, "сокращение sets требует ровно одно из reps/seconds")
    element: dict[str, Any]
    if has_reps:
        element = {"kind": SetKind.REPS.value, "target_reps": data["reps"]}
    else:
        element = {"kind": SetKind.TIME.value, "target_seconds": data["seconds"]}
    if data.get("rest_seconds") is not None:
        element["rest_after_seconds"] = data["rest_seconds"]
    elements = [dict(element) for _ in range(count)]
    elements[-1].pop("rest_after_seconds", None)
    return elements


def _default_prep(kind: BlockKind, first_set: SetPrescription | None, *, is_first_block: bool) -> int:
    """§3.6: 5 с для первого блока тренировки и для блоков, где часы стартуют сразу (первый
    подход time/max_time или интервал); иначе 0 — подготовкой служит предыдущий отдых."""
    if is_first_block or kind is BlockKind.INTERVAL:
        return DEFAULT_PREP_SECONDS
    if first_set is not None and first_set.kind in (SetKind.TIME, SetKind.MAX_TIME):
        return DEFAULT_PREP_SECONDS
    return 0


def _parse_block(
    raw: object,
    path: str,
    *,
    index: int,
    block_count: int,
    default_rest: int,
    visible_exercise_ids: Collection[int] | None,
) -> Block:
    data = _require_mapping(raw, path)
    if "is_extra" in data:
        raise _fail("W8", f"{path}.is_extra", "дополнительные подходы не входят в рецепт")
    _reject_unknown(data, _BLOCK_KEYS, path)

    key = data.get("key")
    if not isinstance(key, str) or not key.strip() or len(key) > 64 or key != key.strip():
        raise _fail("invalid_key", f"{path}.key", "ключ блока — непустая строка ≤ 64 без пробелов по краям")

    exercise_id = _int(data.get("exercise_id"), f"{path}.exercise_id", minimum=1, maximum=2**63 - 1)
    if visible_exercise_ids is not None and exercise_id not in visible_exercise_ids:
        raise _fail("W6", f"{path}.exercise_id", "упражнение недоступно владельцу тренировки")

    kind_raw = data.get("kind")
    if kind_raw is None:
        kind = BlockKind.INTERVAL if data.get("interval") is not None else BlockKind.SETS
    else:
        kind = _enum(BlockKind, kind_raw, f"{path}.kind")

    source = _enum(BlockSource, data.get("source") or BlockSource.STATIC.value, f"{path}.source")
    role_raw = data.get("progression_role")
    progression_role: str | None = None
    if source is BlockSource.PROGRESSION:
        if not isinstance(role_raw, str) or not role_raw.strip():
            raise _fail("W7", f"{path}.progression_role", "progression-блоку нужна роль")
        if kind is not BlockKind.SETS:
            raise _fail("W7", f"{path}.kind", "progression-блок бывает только kind=sets")
        progression_role = role_raw
    elif role_raw is not None:
        raise _fail("W7", f"{path}.progression_role", "роль задаётся только у source=progression")

    sets_raw = data.get("sets")
    interval_raw = data.get("interval")
    shorthand_used = isinstance(sets_raw, int) and not isinstance(sets_raw, bool)
    if not shorthand_used:
        for shorthand_key in ("reps", "seconds", "rest_seconds"):
            if shorthand_key in data:
                raise _fail("invalid_shorthand", f"{path}.{shorthand_key}", "поле сокращения без sets: N")

    sets: tuple[SetPrescription, ...] = ()
    interval: IntervalSpec | None = None
    if kind is BlockKind.SETS:
        if interval_raw is not None:
            raise _fail("W3", f"{path}.interval", "у блока kind=sets нет interval")
        if source is BlockSource.PROGRESSION:
            if sets_raw not in (None, []):
                raise _fail("W7", f"{path}.sets", "у progression-блока подходы задаёт резолвер при старте")
        else:
            if shorthand_used:
                elements: Sequence[object] = _expand_shorthand(data, path)
            elif isinstance(sets_raw, list):
                elements = sets_raw
            else:
                raise _fail("W7", f"{path}.sets", "у статического блока нужен ≥ 1 подход")
            if not elements:
                raise _fail("W7", f"{path}.sets", "у статического блока нужен ≥ 1 подход")
            if len(elements) > MAX_SETS_PER_BLOCK:
                raise _fail("out_of_range", f"{path}.sets", f"не больше {MAX_SETS_PER_BLOCK} подходов")
            parsed = [_parse_set(item, f"{path}.sets[{i}]") for i, item in enumerate(elements)]
            sets = _resolve_set_rests(parsed, default_rest=default_rest, path=f"{path}.sets")
    else:
        if sets_raw is not None:
            raise _fail("W3", f"{path}.sets", "у интервального блока нет sets")
        interval_data = _require_mapping(interval_raw, f"{path}.interval") if interval_raw is not None else None
        if interval_data is None:
            raise _fail("W3", f"{path}.interval", "интервальному блоку нужен interval")
        _reject_unknown(interval_data, _INTERVAL_KEYS, f"{path}.interval")
        record = interval_data.get("record_reps_per_round", False)
        if not isinstance(record, bool):
            raise _fail("invalid_type", f"{path}.interval.record_reps_per_round", "ожидается true/false")
        interval = IntervalSpec(
            work_seconds=_int(interval_data.get("work_seconds"), f"{path}.interval.work_seconds",
                              minimum=1, maximum=MAX_SECONDS),
            rest_seconds=_int(interval_data.get("rest_seconds"), f"{path}.interval.rest_seconds",
                              minimum=0, maximum=MAX_SECONDS),
            rounds=_int(interval_data.get("rounds"), f"{path}.interval.rounds",
                        minimum=1, maximum=MAX_INTERVAL_ROUNDS),
            record_reps_per_round=record,
        )

    extra_raw = data.get("extra_sets_allowed")
    if extra_raw is None:
        extra_sets_allowed = kind is BlockKind.SETS
    elif not isinstance(extra_raw, bool):
        raise _fail("invalid_type", f"{path}.extra_sets_allowed", "ожидается true/false")
    else:
        extra_sets_allowed = extra_raw
    if kind is BlockKind.INTERVAL and extra_sets_allowed:
        raise _fail("invalid_value", f"{path}.extra_sets_allowed", "у интервального блока нет доп. подходов")

    is_last_block = index == block_count - 1
    rest_after_block_raw = data.get("rest_after_block_seconds", _MISSING)
    if is_last_block:
        if rest_after_block_raw is not _MISSING and rest_after_block_raw is not None:
            raise _fail("W4", f"{path}.rest_after_block_seconds", "у последнего блока нет отдыха после блока")
        rest_after_block: int | None = None
    elif rest_after_block_raw is _MISSING or rest_after_block_raw is None:
        rest_after_block = default_rest
    else:
        rest_after_block = _int(rest_after_block_raw, f"{path}.rest_after_block_seconds", minimum=0, maximum=MAX_SECONDS)

    prep_raw = data.get("prep_seconds")
    if prep_raw is None:
        prep_seconds = _default_prep(kind, sets[0] if sets else None, is_first_block=index == 0)
    else:
        prep_seconds = _int(prep_raw, f"{path}.prep_seconds", minimum=0, maximum=MAX_SECONDS)

    return Block(
        key=key, exercise_id=exercise_id, kind=kind, prep_seconds=prep_seconds,
        rest_after_block_seconds=rest_after_block, extra_sets_allowed=extra_sets_allowed,
        load=_parse_load(data.get("load"), f"{path}.load"), source=source,
        progression_role=progression_role, sets=sets, interval=interval,
    )


def normalize(
    raw: Mapping[str, Any] | WorkoutContent,
    *,
    visible_exercise_ids: Collection[int] | None = None,
) -> WorkoutContent:
    """§3.2: write-time нормализация. Детерминирована и идемпотентна:
    normalize(to_dict(normalize(x))) == normalize(x). Невалидный ввод — WorkoutContentError.

    visible_exercise_ids — W6: множество упражнений, видимых владельцу (None — проверку делает
    вызывающий слой, например бэкфилл системного контента, где владелец — сама система)."""
    if isinstance(raw, WorkoutContent):
        raw = to_dict(raw)
    data = _require_mapping(raw, "$")
    if "sets" in data:
        raise _fail("W1", "$.sets", "число подходов задаётся списком подходов блока, не общим полем")
    _reject_unknown(data, _WORKOUT_KEYS, "$")
    schema_version = data.get("schema_version", SCHEMA_VERSION)
    if schema_version != SCHEMA_VERSION:
        raise _fail("invalid_schema_version", "$.schema_version", f"ожидается {SCHEMA_VERSION}")

    title_raw = data.get("title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        raise _fail("invalid_title", "$.title", "нужно непустое название")
    title = title_raw.strip()
    if len(title) > MAX_TITLE_LENGTH:
        raise _fail("invalid_title", "$.title", f"не длиннее {MAX_TITLE_LENGTH} символов")

    default_rest_seconds = _optional_int(
        data.get("default_rest_seconds"), "$.default_rest_seconds", minimum=0, maximum=MAX_SECONDS,
    )
    effective_default_rest = SYSTEM_DEFAULT_REST_SECONDS if default_rest_seconds is None else default_rest_seconds

    blocks_raw = data.get("blocks")
    if not isinstance(blocks_raw, list) or not blocks_raw:
        raise _fail("invalid_blocks", "$.blocks", "нужен хотя бы один блок")
    if len(blocks_raw) > MAX_BLOCKS:
        raise _fail("out_of_range", "$.blocks", f"не больше {MAX_BLOCKS} блоков")
    blocks = tuple(
        _parse_block(
            block_raw, f"$.blocks[{i}]", index=i, block_count=len(blocks_raw),
            default_rest=effective_default_rest, visible_exercise_ids=visible_exercise_ids,
        )
        for i, block_raw in enumerate(blocks_raw)
    )
    seen: set[str] = set()
    for i, block in enumerate(blocks):
        if block.key in seen:
            raise _fail("W5", f"$.blocks[{i}].key", f"ключ блока {block.key!r} повторяется")
        seen.add(block.key)
    return WorkoutContent(title=title, default_rest_seconds=default_rest_seconds, blocks=blocks)


def assert_block_keys_stable(previous: WorkoutContent, new: WorkoutContent) -> None:
    """W5 (вторая половина): ключ блока — его идентичность между версиями. Один и тот же ключ
    не может «переехать» на другое упражнение — это был бы другой блок под старым именем, и
    история/аналитика по ключу перепутались бы. Добавлять/удалять блоки можно."""
    previous_exercise = {block.key: block.exercise_id for block in previous.blocks}
    for i, block in enumerate(new.blocks):
        old = previous_exercise.get(block.key)
        if old is not None and old != block.exercise_id:
            raise _fail("W5", f"$.blocks[{i}].key", f"ключ {block.key!r} уже означает другое упражнение")


# ============================================================================
# Каноническая сериализация и хеш
# ============================================================================


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _load_to_dict(load: LoadSpec | None) -> dict[str, Any] | None:
    if load is None:
        return None
    return {
        "kind": load.kind.value,
        "value_kg": None if load.value_kg is None else _decimal_text(load.value_kg),
        "item_id": load.item_id,
    }


def _set_to_dict(set_: SetPrescription) -> dict[str, Any]:
    return {
        "kind": set_.kind.value,
        "target_reps": set_.target_reps,
        "target_seconds": set_.target_seconds,
        "load": _load_to_dict(set_.load),
        "rest_after_seconds": set_.rest_after_seconds,
        "role": set_.role.value,
    }


def _interval_to_dict(interval: IntervalSpec | None) -> dict[str, Any] | None:
    if interval is None:
        return None
    return {
        "work_seconds": interval.work_seconds,
        "rest_seconds": interval.rest_seconds,
        "rounds": interval.rounds,
        "record_reps_per_round": interval.record_reps_per_round,
    }


def _block_to_dict(block: Block) -> dict[str, Any]:
    return {
        "key": block.key,
        "exercise_id": block.exercise_id,
        "kind": block.kind.value,
        "prep_seconds": block.prep_seconds,
        "rest_after_block_seconds": block.rest_after_block_seconds,
        "extra_sets_allowed": block.extra_sets_allowed,
        "load": _load_to_dict(block.load),
        "source": block.source.value,
        "progression_role": block.progression_role,
        "sets": [_set_to_dict(s) for s in block.sets] if block.kind is BlockKind.SETS else None,
        "interval": _interval_to_dict(block.interval),
    }


def to_dict(content: WorkoutContent) -> dict[str, Any]:
    """Хранимая (JSONB) форма. Все поля присутствуют явно (null, а не отсутствие) — так у
    одного смысла ровно одно представление, и хеш не зависит от того, как ввод был записан."""
    return {
        "schema_version": content.schema_version,
        "title": content.title,
        "default_rest_seconds": content.default_rest_seconds,
        "blocks": [_block_to_dict(b) for b in content.blocks],
    }


def canonical_json(content: WorkoutContent) -> str:
    return json.dumps(to_dict(content), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(content: WorkoutContent) -> str:
    """sha256 канонического JSON (§5). Одинаковый смысл → одинаковый хеш: ввод нормализуется
    до хеширования, а сокращение «3 × 10» и три явных подхода дают один и тот же JSON."""
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


# ============================================================================
# describe() — единственный источник текста рецепта (§3.2, §7)
# ============================================================================

MAX_LABEL = "Максимум"
MAX_TIME_LABEL = "Максимум по времени"
PROGRESSION_LABEL = "По программе"


def format_seconds(seconds: int) -> str:
    """0:30, 3:00, 1:05:00."""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _segments(sets: Sequence[SetPrescription]) -> list[list[SetPrescription]]:
    """Подряд идущие подходы одного вида — один фрагмент описания."""
    segments: list[list[SetPrescription]] = []
    for set_ in sets:
        if segments and segments[-1][0].kind is set_.kind:
            segments[-1].append(set_)
        else:
            segments.append([set_])
    return segments


def _describe_segment(segment: Sequence[SetPrescription]) -> str:
    kind = segment[0].kind
    count = len(segment)
    if kind is SetKind.MAX_REPS:
        return MAX_LABEL if count == 1 else f"{MAX_LABEL} × {count}"
    if kind is SetKind.MAX_TIME:
        return MAX_TIME_LABEL if count == 1 else f"{MAX_TIME_LABEL} × {count}"
    if kind is SetKind.REPS:
        values = [str(s.target_reps) for s in segment]
    else:
        values = [format_seconds(s.target_seconds or 0) for s in segment]
    if len(set(values)) == 1:
        return f"{count} × {values[0]}"
    # Неравномерная последовательность — явно, по порядку; никогда не «среднее × N».
    return "-".join(values)


def _describe_load(load: LoadSpec | None) -> str | None:
    if load is None or load.kind is LoadKind.BODYWEIGHT:
        return None
    if load.kind is LoadKind.BAND:
        return "с резиной"
    value = _decimal_text(load.value_kg or Decimal(0))
    return f"+{value} кг" if load.kind is LoadKind.ADDED_KG else f"−{value} кг"


def describe_sets(
    kind: BlockKind,
    sets: Sequence[SetPrescription],
    interval: IntervalSpec | None,
    *,
    block_load: LoadSpec | None = None,
    source: BlockSource = BlockSource.STATIC,
) -> str:
    if kind is BlockKind.INTERVAL:
        assert interval is not None
        return (
            f"{interval.rounds} × ({format_seconds(interval.work_seconds)} работа / "
            f"{format_seconds(interval.rest_seconds)} отдых)"
        )
    if source is BlockSource.PROGRESSION and not sets:
        return PROGRESSION_LABEL
    text = " + ".join(_describe_segment(segment) for segment in _segments(sets))
    effective_loads = {s.load if s.load is not None else block_load for s in sets}
    if len(effective_loads) == 1:
        load_text = _describe_load(next(iter(effective_loads)))
        if load_text is not None:
            text = f"{text} · {load_text}"
    elif effective_loads:
        text = f"{text} · нагрузка по подходам"
    return text


def describe(block: Block | SnapshotBlock) -> str:
    """«3 × 10», «5-4-3-2-1-…», «Максимум × 4», «3 × 10 + Максимум», «6 × (0:10 работа / 0:20
    отдых)». Чистая функция хранимой формы (или блока снимка)."""
    source = block.source if isinstance(block, Block) else BlockSource.STATIC
    return describe_sets(block.kind, block.sets, block.interval, block_load=block.load, source=source)


def describe_rest(block: Block | SnapshotBlock) -> str | None:
    """Отдых между подходами: «отдых 1:30» (одинаковый) / «отдых 3:00 → 2:00 → 1:00»
    (по подходам) / None (нет пауз). Интервал описывает свой отдых в describe()."""
    if block.kind is BlockKind.INTERVAL:
        return None
    rests = [s.rest_after_seconds for s in block.sets if s.rest_after_seconds is not None]
    if not rests or all(r == 0 for r in rests):
        return None
    if len(set(rests)) == 1:
        return f"отдых {format_seconds(rests[0])}"
    return "отдых " + " → ".join(format_seconds(r) for r in rests)


def describe_workout(content: WorkoutContent, exercise_names: Mapping[int, str]) -> list[str]:
    """По строке на блок: «Подтягивания: 3 × 10 + Максимум · отдых 4:00»."""
    lines: list[str] = []
    for block in content.blocks:
        name = exercise_names.get(block.exercise_id) or f"Упражнение #{block.exercise_id}"
        text = f"{name}: {describe(block)}"
        rest = describe_rest(block)
        if rest is not None:
            text = f"{text} · {rest}"
        lines.append(text)
    return lines


def total_target_reps(block: Block | SnapshotBlock) -> int | None:
    """Сумма целевых повторений блока (W-лесенка: 53); None, если в блоке есть подход без
    числовой цели (максимум/время/интервал)."""
    if block.kind is not BlockKind.SETS or not block.sets:
        return None
    if any(s.kind is not SetKind.REPS for s in block.sets):
        return None
    return sum(s.target_reps or 0 for s in block.sets)


# ============================================================================
# PrescriptionSnapshot (§5, S1–S4)
# ============================================================================


@dataclass(frozen=True)
class ExerciseInfo:
    """Что снимок замораживает об упражнении (E1, E2, E4)."""

    id: int
    display_name: str
    analytics_exercise_id: int
    category_id: int | None


@dataclass(frozen=True)
class SnapshotProvenance:
    kind: BlockSource
    resolved_at: datetime
    program_inclusion_id: int | None = None
    strategy: str | None = None
    progression_state_rev: int | None = None


@dataclass(frozen=True)
class SnapshotBlock:
    """Разрешённый блок снимка: всегда конкретные подходы, без маркера progression (S3)."""

    key: str
    exercise_id: int
    exercise_display_name: str
    analytics_exercise_id: int
    category_id: int | None
    kind: BlockKind
    prep_seconds: int
    rest_after_block_seconds: int | None
    extra_sets_allowed: bool
    load: LoadSpec | None
    sets: tuple[SetPrescription, ...]
    interval: IntervalSpec | None


@dataclass(frozen=True)
class PrescriptionSnapshot:
    workout_definition_id: int | None
    workout_definition_version_id: int | None
    version_no: int | None
    title: str
    blocks: tuple[SnapshotBlock, ...]
    provenance: SnapshotProvenance
    synthesized: bool = False
    snapshot_schema: int = SNAPSHOT_SCHEMA_VERSION


class SnapshotResolutionError(ValueError):
    """Снимок нельзя построить: нет резолвера для progression-блока, резолвер вернул рецепт,
    нарушающий инварианты (например цель 0 — класс бага D3), или нет данных упражнения."""


ProgressionBlockResolver = Callable[[str], Sequence[Mapping[str, Any] | SetPrescription]]
"""role → подходы блока. Интерфейс resolve_progression_block(role, progression_state) из §6:
вызывающий код связывает progression_state заранее. Числа (цели, число подходов, наличие
завершающего max-подхода) — не этот модуль: #305, OD-1/OD-3."""


def _coerce_resolved_sets(
    role: str, resolved: Sequence[Mapping[str, Any] | SetPrescription], *, default_rest: int, path: str,
) -> tuple[SetPrescription, ...]:
    raw_sets: list[Any] = []
    for item in resolved:
        raw_sets.append(_set_to_dict(item) if isinstance(item, SetPrescription) else dict(item))
    if not raw_sets:
        raise SnapshotResolutionError(f"резолвер роли {role!r} не вернул ни одного подхода")
    # Последний подход: W4 — rest None. Резолвер возвращает подходы целиком (с отдыхом последнего
    # = None); прочие проверки — те же, что у статического блока.
    try:
        parsed = [_parse_set(item, f"{path}[{i}]") for i, item in enumerate(raw_sets)]
        return _resolve_set_rests(parsed, default_rest=default_rest, path=path)
    except WorkoutContentError as exc:
        raise SnapshotResolutionError(f"резолвер роли {role!r}: {exc}") from exc


def build_prescription_snapshot(
    content: WorkoutContent,
    *,
    workout_definition_id: int | None,
    workout_definition_version_id: int | None,
    version_no: int | None,
    exercises: Mapping[int, ExerciseInfo],
    resolved_at: datetime,
    resolve_progression: ProgressionBlockResolver | None = None,
    program_inclusion_id: int | None = None,
    strategy: str | None = None,
    progression_state_rev: int | None = None,
) -> PrescriptionSnapshot:
    """Самодостаточный разрешённый снимок рецепта (§5). Не пишет в БД — запись снимка в
    TrainingSession — Wave 3a (#307)."""
    default_rest = (
        SYSTEM_DEFAULT_REST_SECONDS if content.default_rest_seconds is None else content.default_rest_seconds
    )
    blocks: list[SnapshotBlock] = []
    used_progression = False
    for index, block in enumerate(content.blocks):
        info = exercises.get(block.exercise_id)
        if info is None:
            raise SnapshotResolutionError(f"нет данных упражнения {block.exercise_id} для блока {block.key!r}")
        sets = block.sets
        if block.source is BlockSource.PROGRESSION:
            if resolve_progression is None:
                raise SnapshotResolutionError(f"блок {block.key!r} требует резолвер прогрессии")
            assert block.progression_role is not None
            sets = _coerce_resolved_sets(
                block.progression_role, resolve_progression(block.progression_role),
                default_rest=default_rest, path=f"$.blocks[{index}].sets",
            )
            used_progression = True
        blocks.append(SnapshotBlock(
            key=block.key, exercise_id=block.exercise_id, exercise_display_name=info.display_name,
            analytics_exercise_id=info.analytics_exercise_id, category_id=info.category_id,
            kind=block.kind, prep_seconds=block.prep_seconds,
            rest_after_block_seconds=block.rest_after_block_seconds,
            extra_sets_allowed=block.extra_sets_allowed, load=block.load, sets=sets,
            interval=block.interval,
        ))
    provenance = SnapshotProvenance(
        kind=BlockSource.PROGRESSION if used_progression else BlockSource.STATIC,
        resolved_at=resolved_at,
        program_inclusion_id=program_inclusion_id if used_progression else None,
        strategy=strategy if used_progression else None,
        progression_state_rev=progression_state_rev if used_progression else None,
    )
    return PrescriptionSnapshot(
        workout_definition_id=workout_definition_id,
        workout_definition_version_id=workout_definition_version_id,
        version_no=version_no, title=content.title, blocks=tuple(blocks), provenance=provenance,
    )


def snapshot_to_dict(snapshot: PrescriptionSnapshot) -> dict[str, Any]:
    p = snapshot.provenance
    return {
        "snapshot_schema": snapshot.snapshot_schema,
        "workout_definition_id": snapshot.workout_definition_id,
        "workout_definition_version_id": snapshot.workout_definition_version_id,
        "version_no": snapshot.version_no,
        "title": snapshot.title,
        "synthesized": snapshot.synthesized,
        "blocks": [
            {
                "key": b.key, "exercise_id": b.exercise_id,
                "exercise_display_name": b.exercise_display_name,
                "analytics_exercise_id": b.analytics_exercise_id, "category_id": b.category_id,
                "kind": b.kind.value, "prep_seconds": b.prep_seconds,
                "rest_after_block_seconds": b.rest_after_block_seconds,
                "extra_sets_allowed": b.extra_sets_allowed, "load": _load_to_dict(b.load),
                "sets": [_set_to_dict(s) for s in b.sets] if b.kind is BlockKind.SETS else None,
                "interval": _interval_to_dict(b.interval),
            }
            for b in snapshot.blocks
        ],
        "provenance": {
            "kind": p.kind.value, "resolved_at": p.resolved_at.isoformat(),
            "program_inclusion_id": p.program_inclusion_id, "strategy": p.strategy,
            "progression_state_rev": p.progression_state_rev,
        },
    }


def snapshot_from_dict(data: Mapping[str, Any]) -> PrescriptionSnapshot:
    """Чтение сохранённого снимка (JSON). Снимок уже прошёл проверку при построении, поэтому
    здесь только обратная конвертация; кривой JSON — WorkoutContentError."""
    if data.get("snapshot_schema") != SNAPSHOT_SCHEMA_VERSION:
        raise _fail("invalid_schema_version", "$.snapshot_schema", f"ожидается {SNAPSHOT_SCHEMA_VERSION}")
    blocks: list[SnapshotBlock] = []
    for i, raw in enumerate(data["blocks"]):
        path = f"$.blocks[{i}]"
        kind = _enum(BlockKind, raw["kind"], f"{path}.kind")
        interval_raw = raw.get("interval")
        sets: tuple[SetPrescription, ...] = ()
        if kind is BlockKind.SETS:
            parsed = [_parse_set(item, f"{path}.sets[{j}]") for j, item in enumerate(raw["sets"])]
            sets = tuple(
                _replace_rest(set_, raw["sets"][j]["rest_after_seconds"]) for j, (set_, _) in enumerate(parsed)
            )
        blocks.append(SnapshotBlock(
            key=raw["key"], exercise_id=raw["exercise_id"],
            exercise_display_name=raw["exercise_display_name"],
            analytics_exercise_id=raw["analytics_exercise_id"], category_id=raw.get("category_id"),
            kind=kind, prep_seconds=raw["prep_seconds"],
            rest_after_block_seconds=raw.get("rest_after_block_seconds"),
            extra_sets_allowed=raw["extra_sets_allowed"],
            load=_parse_load(raw.get("load"), f"{path}.load"), sets=sets,
            interval=None if interval_raw is None else IntervalSpec(**interval_raw),
        ))
    p = data["provenance"]
    return PrescriptionSnapshot(
        workout_definition_id=data.get("workout_definition_id"),
        workout_definition_version_id=data.get("workout_definition_version_id"),
        version_no=data.get("version_no"), title=data["title"], blocks=tuple(blocks),
        provenance=SnapshotProvenance(
            kind=BlockSource(p["kind"]), resolved_at=datetime.fromisoformat(p["resolved_at"]),
            program_inclusion_id=p.get("program_inclusion_id"), strategy=p.get("strategy"),
            progression_state_rev=p.get("progression_state_rev"),
        ),
        synthesized=bool(data.get("synthesized", False)),
    )


# ============================================================================
# V1 → v2 (§8, MIGRATION §3)
# ============================================================================


class V1MappingError(ValueError):
    """V1-данные неоднозначны — версия не создаётся, тренировка помечается для разбора
    (MIGRATION §3). Никаких догадок о смысле."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class V1Item:
    """Одна строка complex_items (голова тренировки V1)."""

    item_id: int
    exercise_id: int
    order_index: int
    protocol: Mapping[str, Any] | None
    sets: int = 0
    target_value: Decimal | None = None
    target_unit: str | None = None
    rest_seconds: int | None = None
    progression_role: str | None = field(default=None)


def v1_block_key(item_id: int) -> str:
    """Ключ блока для V1-головы — id строки complex_items: стабилен между версиями, пока
    строка жива (W5), и одинаков при повторной конвертации (идемпотентность)."""
    return f"i{item_id}"


def _v1_rests(count: int, rest: int) -> list[dict[str, Any]]:
    return [{"rest_after_seconds": rest} if i < count - 1 else {} for i in range(count)]


def _v1_protocol_block(item: V1Item) -> dict[str, Any]:
    protocol = dict(item.protocol or {})
    protocol_type = protocol.get("type")
    prescription = protocol.get("prescription") if isinstance(protocol.get("prescription"), Mapping) else {}
    source = prescription.get("source", "static")
    rest = protocol.get("rest_seconds", 0)
    base: dict[str, Any] = {"key": v1_block_key(item.item_id), "exercise_id": item.exercise_id}

    if protocol_type == "reps_sets" and source == "progression":
        if not item.progression_role:
            raise V1MappingError(f"item {item.item_id}: progression reps_sets без роли упражнения")
        return {**base, "kind": "sets", "source": "progression", "progression_role": item.progression_role}
    if protocol_type == "reps_sets" and source == "static":
        count, reps = prescription.get("sets"), prescription.get("reps")
        if not isinstance(count, int) or not isinstance(reps, int):
            raise V1MappingError(f"item {item.item_id}: reps_sets без sets/reps")
        return {**base, "kind": "sets", "sets": [
            {"kind": "reps", "target_reps": reps, **extra} for extra in _v1_rests(count, rest)
        ]}
    if protocol_type == "time_sets" and source == "static":
        count, seconds = prescription.get("sets"), prescription.get("duration_seconds")
        if not isinstance(count, int) or not isinstance(seconds, int):
            raise V1MappingError(f"item {item.item_id}: time_sets без sets/duration_seconds")
        return {**base, "kind": "sets", "sets": [
            {"kind": "time", "target_seconds": seconds, **extra} for extra in _v1_rests(count, rest)
        ]}
    if protocol_type == "time_sets":
        raise V1MappingError(f"item {item.item_id}: progression time_sets не поддерживается")
    if protocol_type == "max_effort":
        attempts = prescription.get("attempts")
        if not isinstance(attempts, int):
            raise V1MappingError(f"item {item.item_id}: max_effort без attempts")
        return {**base, "kind": "sets", "sets": [
            {"kind": "max_reps", **extra} for extra in _v1_rests(attempts, rest)
        ]}
    if protocol_type == "interval":
        total, work, pause = (
            protocol.get("total_duration_seconds"), protocol.get("work_seconds"), protocol.get("rest_seconds"),
        )
        if not all(isinstance(v, int) for v in (total, work, pause)) or work + pause <= 0:
            raise V1MappingError(f"item {item.item_id}: interval без длительностей")
        if total % (work + pause) != 0:
            raise V1MappingError(
                f"item {item.item_id}: interval {total} с не делится на цикл {work}+{pause} — раундов не определить",
            )
        return {**base, "kind": "interval", "interval": {
            "work_seconds": work, "rest_seconds": pause, "rounds": total // (work + pause),
            "record_reps_per_round": False,
        }}
    raise V1MappingError(f"item {item.item_id}: неизвестный протокол {protocol_type!r}")


def _v1_legacy_block(item: V1Item) -> dict[str, Any]:
    """Строка без protocol (до ExecutionProtocol v1): sets/target_value/target_unit.
    Только однозначные случаи: целое значение ≥ 1 и единица «reps» или «s»."""
    value = item.target_value
    if item.sets < 1 or value is None or value != value.to_integral_value() or value < 1:
        raise V1MappingError(f"item {item.item_id}: legacy-строка без однозначной цели")
    rest = item.rest_seconds if item.rest_seconds is not None else 0
    base = {"key": v1_block_key(item.item_id), "exercise_id": item.exercise_id, "kind": "sets"}
    if item.target_unit == "reps":
        return {**base, "sets": [
            {"kind": "reps", "target_reps": int(value), **extra} for extra in _v1_rests(item.sets, rest)
        ]}
    if item.target_unit == "s":
        return {**base, "sets": [
            {"kind": "time", "target_seconds": int(value), **extra} for extra in _v1_rests(item.sets, rest)
        ]}
    raise V1MappingError(f"item {item.item_id}: legacy-единица {item.target_unit!r} неоднозначна")


def content_from_v1(title: str, items: Sequence[V1Item]) -> WorkoutContent:
    """Детерминированное V1 → v2 (§8). Порядок блоков — order_index, затем id. Отдых между
    блоками V1 не хранил — остаётся умолчание (тот же DEFAULT_REST_SECONDS, что применяет живая
    сессия V1). Пустая тренировка или неоднозначная строка — V1MappingError."""
    if not items:
        raise V1MappingError("в тренировке нет упражнений")
    ordered = sorted(items, key=lambda item: (item.order_index, item.item_id))
    blocks = [
        _v1_protocol_block(item) if item.protocol is not None else _v1_legacy_block(item)
        for item in ordered
    ]
    try:
        return normalize({"title": title, "blocks": blocks})
    except WorkoutContentError as exc:
        raise V1MappingError(f"V1 → v2 нарушает инвариант: {exc}") from exc
