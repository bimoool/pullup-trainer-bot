"""Замороженный бэкфилл ревизии b7d2e9f4a1c3 (WorkoutDefinition v2, issue #303, review B2).

Привязан к ревизии b7d2e9f4a1c3 и НЕ меняется после её выпуска. Импортирует только stdlib и
SQLAlchemy — ни app.domain.workout_definition, ни app.domain.exercise_identity, ни модели/сервисы
(WORKOUT_DOMAIN_V2 §9.10). Содержит всё, что нужно ревизии:

- подмножество V1 → v2 (WORKOUT_DOMAIN_V2 §8) и нормализации, достижимое из V1-головы, с
  умолчаниями этой ревизии (отдых 90 с, подготовка 5 с, роли подходов, потолки ввода);
- каноническую сериализацию schema_version = 2 и sha256;
- сиды/карты категорий, slug системных упражнений, литералы переписанного системного контента;
- запись версий по правилу этой ревизии: append-only, no-op только против ТЕКУЩЕЙ версии
  (WORKOUT_DOMAIN_V2 §5, решение владельца B1), W5 — по ключам всех прежних версий.

Эквивалентность с рантаймом НА СЕГОДНЯ доказывают parity-тесты
(tests/test_scripts/test_frozen_b7d2e9f4a1c3_parity.py); буквальные golden-хеши системного
контента там же не правятся никогда — даже если рантайм-семантика позже намеренно изменится.

MIGRATION_V2 §3: порядок ORDER BY id, натуральные ключи, ON CONFLICT DO NOTHING, повторный
прогон = 0 изменений. Не трогает подписки, доступ, планы, включения, сессии и историю.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

REVISION = "b7d2e9f4a1c3"

# --- Умолчания и потолки ревизии (копия значений на 2026-10-08) -----------------------------

SCHEMA_VERSION = 2
DEFAULT_REST_SECONDS = 90
DEFAULT_PREP_SECONDS = 5
MAX_SETS_PER_BLOCK = 100
MAX_BLOCKS = 50
MAX_TARGET_REPS = 999
MAX_SECONDS = 86_400
MAX_INTERVAL_ROUNDS = 1_000
MAX_TITLE_LENGTH = 255
MAX_ID = 2**63 - 1

ROLE_SUBCATEGORIES = ("block_a", "block_b")
CANONICAL_PULL_UP_NAME = "Подтягивания"

# --- Категории и упражнения (копия app.domain.exercise_identity на 2026-10-08) --------------

CATEGORY_PULL_UPS = "pull_ups"
CATEGORY_MY_EXERCISES = "my_exercises"
CATEGORY_UNCATEGORIZED = "uncategorized"

# (slug, display_name, parent_slug, sort_order, is_service)
CATEGORY_SEEDS: tuple[tuple[str, str, str | None, int, bool], ...] = (
    ("pull_ups", "Подтягивания", None, 10, False),
    ("grip", "Хват", None, 20, False),
    ("general_fitness", "Общая физическая подготовка", None, 30, False),
    ("my_exercises", "Мои упражнения", None, 90, False),
    ("uncategorized", "Без категории", None, 99, False),
    ("block_a", "Блок A — объём", "pull_ups", 11, True),
    ("block_b", "Блок Б — сила", "pull_ups", 12, True),
    ("elective_max_reps_ladder", "Факультатив — на максимум", "pull_ups", 13, True),
    ("elective_w_ladder", "Факультатив — W", "pull_ups", 14, True),
    ("elective_three_minutes", "Факультатив — 3 минуты", "pull_ups", 15, True),
    ("elective_volume_target", "Факультатив — на объём", "pull_ups", 16, True),
)

LEGACY_CATEGORY_TO_SLUG: dict[str, str] = {
    "pull_ups": "pull_ups",
    "Подтягивания": "pull_ups",
    "Хват": "grip",
    "Общая физическая подготовка": "general_fitness",
    "user": "my_exercises",
}
LEGACY_SUBCATEGORY_TO_SLUG: dict[str, str] = {
    "block_a": "block_a",
    "block_b": "block_b",
    "elective_max_reps_ladder": "elective_max_reps_ladder",
    "elective_w_ladder": "elective_w_ladder",
    "elective_three_minutes": "elective_three_minutes",
    "elective_volume_target": "elective_volume_target",
}

SYSTEM_EXERCISE_SLUGS: dict[str, str] = {
    "Подтягивания": "pull_up",
    "Подтягивания с резиной": "pull_up_band",
    "Подтягивания с отягощением": "pull_up_weighted",
    "Австралийские подтягивания": "australian_pull_up",
    "Лопаточные подтягивания": "scapular_pull_up",
    "Вис на турнике": "dead_hang",
    "Планка": "plank",
    "Отжимания": "push_up",
    "Подтягивания — объём": "course_block_a",
    "Подтягивания — сила": "course_block_b",
    "Факультатив — подтягивания на максимум": "elective_max_reps_ladder",
    "Факультатив — подтягивания W": "elective_w_ladder",
    "Факультатив — 3 минуты подтягиваний": "elective_three_minutes",
    "Факультатив — подтягивания на объём": "elective_volume_target",
}

# --- Системный контент ---------------------------------------------------------------------

# Голова V1, которую положил сид a4c8e1f7b2d9. Переписываем, только если голова в точности такая
# (владелец мог отредактировать системную тренировку — тогда не угадываем, а сообщаем).
SEEDED_V1_PROTOCOLS: dict[str, dict[str, Any]] = {
    "Максимум подтягиваний": {
        "type": "max_effort", "prescription": {"source": "static", "attempts": 4}, "rest_seconds": 120,
    },
    "W-лесенка": {
        "type": "reps_sets", "prescription": {"source": "static", "sets": 17, "reps": 3}, "rest_seconds": 10,
    },
    "3 минуты подтягиваний": {
        "type": "interval", "total_duration_seconds": 180, "work_seconds": 10, "rest_seconds": 20,
        "starts_with": "work",
    },
}

# app.domain.electives на 2026-10-08 — копия значений.
W_LADDER_TARGETS: tuple[int, ...] = (5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5)
W_LADDER_REST_SECONDS = 10
MAX_LADDER_RESTS: tuple[int, ...] = (180, 120, 60)
MAX_LADDER_SETS = 4
THREE_MINUTES_INTERVAL: dict[str, Any] = {
    "work_seconds": 10, "rest_seconds": 20, "rounds": 6, "record_reps_per_round": True,
}


# ============================================================================
# Каноническая форма schema_version = 2
# ============================================================================


class MappingError(ValueError):
    """V1-данные неоднозначны/невалидны — версия не создаётся, тренировка в отчёте."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def canonical_json(stored: Mapping[str, Any]) -> str:
    return json.dumps(stored, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(stored: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(stored).encode("utf-8")).hexdigest()


def block_key(item_id: int, exercise_id: int) -> str:
    return f"i{item_id}e{exercise_id}"


def _int(value: object, what: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MappingError(f"{what}: ожидается целое число")
    if value < minimum or value > maximum:
        raise MappingError(f"{what}: допустимо {minimum}…{maximum}, получено {value}")
    return value


def _set(kind: str, *, reps: int | None = None, seconds: int | None = None, rest: int | None) -> dict[str, Any]:
    return {
        "kind": kind, "target_reps": reps, "target_seconds": seconds, "load": None,
        "rest_after_seconds": rest, "role": "max" if kind in ("max_reps", "max_time") else "working",
    }


def _sets(count: object, rest: object, what: str, make: Any) -> list[dict[str, Any]]:
    """count одинаковых подходов; отдых не-последнего = rest ?? 90 (rest проверяется, только
    если не-последний подход есть), у последнего — None."""
    if isinstance(count, bool) or not isinstance(count, int):
        count = int(count)  # bool → 0/1, как range() в рантайме этой ревизии
    if count < 1:
        raise MappingError(f"{what}: у статического блока нужен ≥ 1 подход")
    if count > MAX_SETS_PER_BLOCK:
        raise MappingError(f"{what}: не больше {MAX_SETS_PER_BLOCK} подходов")
    between: int | None = None
    if count > 1:
        between = DEFAULT_REST_SECONDS if rest is None else _int(rest, f"{what}.rest", minimum=0, maximum=MAX_SECONDS)
    return [make(between if i < count - 1 else None) for i in range(count)]


def _block(
    key: str, exercise_id: int, *, kind: str = "sets", sets: list[dict[str, Any]] | None = None,
    interval: dict[str, Any] | None = None, source: str = "static", progression_role: str | None = None,
) -> dict[str, Any]:
    """Блок в хранимой форме; prep/rest_after_block проставляет _finish (зависят от позиции)."""
    return {
        "key": key, "exercise_id": exercise_id, "kind": kind, "prep_seconds": None,
        "rest_after_block_seconds": None, "extra_sets_allowed": kind == "sets", "load": None,
        "source": source, "progression_role": progression_role,
        "sets": (sets or []) if kind == "sets" else None, "interval": interval,
    }


def _finish(title: object, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(title, str) or not title.strip():
        raise MappingError("нужно непустое название")
    title = title.strip()
    if len(title) > MAX_TITLE_LENGTH:
        raise MappingError(f"название длиннее {MAX_TITLE_LENGTH} символов")
    if not blocks:
        raise MappingError("в тренировке нет упражнений")
    if len(blocks) > MAX_BLOCKS:
        raise MappingError(f"не больше {MAX_BLOCKS} блоков")
    keys: set[str] = set()
    for index, block in enumerate(blocks):
        if block["key"] in keys:
            raise MappingError(f"ключ блока {block['key']!r} повторяется")
        keys.add(block["key"])
        _int(block["exercise_id"], f"block {block['key']}.exercise_id", minimum=1, maximum=MAX_ID)
        first = block["sets"][0] if block["sets"] else None
        if index == 0 or block["kind"] == "interval" or (first is not None and first["kind"] in ("time", "max_time")):
            block["prep_seconds"] = DEFAULT_PREP_SECONDS
        else:
            block["prep_seconds"] = 0
        block["rest_after_block_seconds"] = None if index == len(blocks) - 1 else DEFAULT_REST_SECONDS
    return {"schema_version": SCHEMA_VERSION, "title": title, "default_rest_seconds": None, "blocks": blocks}


# ============================================================================
# V1 → v2 (WORKOUT_DOMAIN_V2 §8) — подмножество этой ревизии
# ============================================================================


@dataclass(frozen=True)
class V1Item:
    item_id: int
    exercise_id: int
    order_index: int
    protocol: Any
    sets: int = 0
    target_value: Decimal | None = None
    target_unit: str | None = None
    rest_seconds: int | None = None
    progression_role: str | None = None


def _protocol_block(item: V1Item) -> dict[str, Any]:
    if not isinstance(item.protocol, Mapping):
        raise MappingError(f"item {item.item_id}: protocol не объект")
    protocol = dict(item.protocol)
    protocol_type = protocol.get("type")
    prescription = protocol.get("prescription") if isinstance(protocol.get("prescription"), Mapping) else {}
    source = prescription.get("source", "static")
    rest = protocol.get("rest_seconds", 0)
    key, what = block_key(item.item_id, item.exercise_id), f"item {item.item_id}"

    if protocol_type == "reps_sets" and source == "progression":
        if not item.progression_role:
            raise MappingError(f"{what}: progression reps_sets без роли упражнения")
        return _block(key, item.exercise_id, source="progression", progression_role=item.progression_role)
    if protocol_type == "reps_sets" and source == "static":
        count, reps = prescription.get("sets"), prescription.get("reps")
        if not isinstance(count, int) or not isinstance(reps, int):
            raise MappingError(f"{what}: reps_sets без sets/reps")
        sets = _sets(count, rest, what, lambda r: _set("reps", reps=reps, rest=r))
        _int(reps, f"{what}.reps", minimum=1, maximum=MAX_TARGET_REPS)
        return _block(key, item.exercise_id, sets=sets)
    if protocol_type == "time_sets" and source == "static":
        count, seconds = prescription.get("sets"), prescription.get("duration_seconds")
        if not isinstance(count, int) or not isinstance(seconds, int):
            raise MappingError(f"{what}: time_sets без sets/duration_seconds")
        sets = _sets(count, rest, what, lambda r: _set("time", seconds=seconds, rest=r))
        _int(seconds, f"{what}.duration_seconds", minimum=1, maximum=MAX_SECONDS)
        return _block(key, item.exercise_id, sets=sets)
    if protocol_type == "time_sets":
        raise MappingError(f"{what}: progression time_sets не поддерживается")
    if protocol_type == "max_effort":
        attempts = prescription.get("attempts")
        if not isinstance(attempts, int):
            raise MappingError(f"{what}: max_effort без attempts")
        return _block(key, item.exercise_id, sets=_sets(attempts, rest, what, lambda r: _set("max_reps", rest=r)))
    if protocol_type == "interval":
        total, work, pause = (
            protocol.get("total_duration_seconds"), protocol.get("work_seconds"), protocol.get("rest_seconds"),
        )
        if not all(isinstance(v, int) for v in (total, work, pause)) or work + pause <= 0:
            raise MappingError(f"{what}: interval без длительностей")
        if total % (work + pause) != 0:
            raise MappingError(f"{what}: interval {total} с не делится на цикл {work}+{pause} — раундов не определить")
        interval = {
            "work_seconds": _int(work, f"{what}.work_seconds", minimum=1, maximum=MAX_SECONDS),
            "rest_seconds": _int(pause, f"{what}.rest_seconds", minimum=0, maximum=MAX_SECONDS),
            "rounds": _int(total // (work + pause), f"{what}.rounds", minimum=1, maximum=MAX_INTERVAL_ROUNDS),
            "record_reps_per_round": False,
        }
        return _block(key, item.exercise_id, kind="interval", interval=interval)
    raise MappingError(f"{what}: неизвестный протокол {protocol_type!r}")


def _legacy_block(item: V1Item) -> dict[str, Any]:
    """Строка без protocol: только целое значение ≥ 1 и единица «reps» или «s»."""
    value = item.target_value
    what = f"item {item.item_id}"
    if item.sets < 1 or value is None or value != value.to_integral_value() or value < 1:
        raise MappingError(f"{what}: legacy-строка без однозначной цели")
    rest = item.rest_seconds if item.rest_seconds is not None else 0
    key = block_key(item.item_id, item.exercise_id)
    if item.target_unit == "reps":
        reps = _int(int(value), f"{what}.target_value", minimum=1, maximum=MAX_TARGET_REPS)
        return _block(key, item.exercise_id, sets=_sets(item.sets, rest, what, lambda r: _set("reps", reps=reps, rest=r)))
    if item.target_unit == "s":
        seconds = _int(int(value), f"{what}.target_value", minimum=1, maximum=MAX_SECONDS)
        return _block(
            key, item.exercise_id, sets=_sets(item.sets, rest, what, lambda r: _set("time", seconds=seconds, rest=r)),
        )
    raise MappingError(f"{what}: legacy-единица {item.target_unit!r} неоднозначна")


def content_from_v1(title: str, items: Sequence[V1Item]) -> dict[str, Any]:
    """V1-голова → хранимая форма schema 2. Порядок блоков — order_index, затем id."""
    if not items:
        raise MappingError("в тренировке нет упражнений")
    ordered = sorted(items, key=lambda item: (item.order_index, item.item_id))
    blocks = [_protocol_block(item) if item.protocol is not None else _legacy_block(item) for item in ordered]
    return _finish(title, blocks)


def reauthored_system_content(title: str, *, item_id: int, exercise_id: int) -> dict[str, Any] | None:
    """v2-рецепт системной тренировки этой ревизии или None — не из списка."""
    key = block_key(item_id, exercise_id)
    if title == "W-лесенка":
        last = len(W_LADDER_TARGETS) - 1
        sets = [
            _set("reps", reps=r, rest=None if i == last else W_LADDER_REST_SECONDS)
            for i, r in enumerate(W_LADDER_TARGETS)
        ]
        block = _block(key, exercise_id, sets=sets)
    elif title == "Максимум подтягиваний":
        rests: list[int | None] = [*MAX_LADDER_RESTS, None]
        block = _block(key, exercise_id, sets=[_set("max_reps", rest=rests[i]) for i in range(MAX_LADDER_SETS)])
    elif title == "3 минуты подтягиваний":
        block = _block(key, exercise_id, kind="interval", interval=dict(THREE_MINUTES_INTERVAL))
    else:
        return None
    return _finish(title, [block])


# ============================================================================
# Запись версий (правило этой ревизии)
# ============================================================================


@dataclass
class BackfillReport:
    categories_inserted: int = 0
    exercises_display_name: int = 0
    exercises_category: int = 0
    exercises_subcategory: int = 0
    exercises_visibility: int = 0
    exercises_analytics_identity: int = 0
    exercises_slug: int = 0
    unknown_categories: list[str] = field(default_factory=list)
    versions_created: int = 0
    current_version_set: int = 0
    current_version_cleared: int = 0
    reauthored: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return (
            self.categories_inserted + self.exercises_display_name + self.exercises_category
            + self.exercises_subcategory + self.exercises_visibility + self.exercises_analytics_identity
            + self.exercises_slug + self.versions_created + self.current_version_set
            + self.current_version_cleared
        )


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _current_version(conn: Connection, workout_definition_id: int) -> Any:
    return conn.execute(
        sa.text(
            "SELECT v.id, v.version_no, v.content_hash FROM complexes c "
            "JOIN workout_definition_versions v ON v.id = c.current_version_id WHERE c.id = :id"
        ),
        {"id": workout_definition_id},
    ).first()


def save_version(conn: Connection, workout_definition_id: int, stored: dict[str, Any]) -> tuple[int, int, bool]:
    """(version_id, version_no, created). Append-only: содержимое = текущей версии — no-op;
    иначе version_no = max + 1 (A → B → A = v1, v2, v3). W5 — по ключам всех прежних версий."""
    digest = content_hash(stored)
    conn.execute(sa.text("SELECT id FROM complexes WHERE id = :id FOR UPDATE"), {"id": workout_definition_id})
    current = _current_version(conn, workout_definition_id)
    if current is not None and current.content_hash == digest:
        return current.id, current.version_no, False
    history = conn.execute(
        sa.text(
            "SELECT DISTINCT b.value ->> 'key' AS key, (b.value ->> 'exercise_id')::bigint AS exercise_id "
            "FROM workout_definition_versions v "
            "CROSS JOIN LATERAL jsonb_array_elements(v.content -> 'blocks') AS b(value) "
            "WHERE v.workout_definition_id = :id"
        ),
        {"id": workout_definition_id},
    ).all()
    known: dict[str, set[int]] = {}
    for row in history:
        known.setdefault(row.key, set()).add(row.exercise_id)
    for block in stored["blocks"]:
        if known.get(block["key"], {block["exercise_id"]}) != {block["exercise_id"]}:
            raise MappingError(f"W5: ключ {block['key']!r} уже означает другое упражнение")
    next_no = conn.execute(
        sa.text(
            "SELECT COALESCE(MAX(version_no), 0) + 1 FROM workout_definition_versions "
            "WHERE workout_definition_id = :id"
        ),
        {"id": workout_definition_id},
    ).scalar_one()
    row = conn.execute(
        sa.text(
            "INSERT INTO workout_definition_versions "
            "(workout_definition_id, version_no, schema_version, content, content_hash) "
            "VALUES (:id, :no, :schema, CAST(:content AS jsonb), :hash) RETURNING id"
        ),
        {
            "id": workout_definition_id, "no": next_no, "schema": SCHEMA_VERSION,
            "content": json.dumps(stored, ensure_ascii=False), "hash": digest,
        },
    ).scalar_one()
    return row, next_no, True


def set_current_version(conn: Connection, workout_definition_id: int, version_id: int | None) -> bool:
    result = conn.execute(
        sa.text(
            "UPDATE complexes SET current_version_id = :version_id "
            "WHERE id = :id AND current_version_id IS DISTINCT FROM :version_id"
        ),
        {"id": workout_definition_id, "version_id": version_id},
    )
    return result.rowcount > 0


def load_v1_items(conn: Connection, workout_definition_id: int) -> list[V1Item]:
    rows = conn.execute(
        sa.text(
            "SELECT ci.id, ci.exercise_id, ci.order_index, ci.protocol, ci.sets, ci.target_value, "
            "ci.target_unit, ci.rest_seconds, e.subcategory "
            "FROM complex_items ci JOIN exercises e ON e.id = ci.exercise_id "
            "WHERE ci.complex_id = :id ORDER BY ci.order_index, ci.id"
        ),
        {"id": workout_definition_id},
    ).all()
    return [
        V1Item(
            item_id=row.id, exercise_id=row.exercise_id, order_index=row.order_index,
            protocol=_json(row.protocol), sets=row.sets,
            target_value=None if row.target_value is None else Decimal(row.target_value),
            target_unit=row.target_unit, rest_seconds=row.rest_seconds,
            progression_role=row.subcategory if row.subcategory in ROLE_SUBCATEGORIES else None,
        )
        for row in rows
    ]


# ============================================================================
# Шаги бэкфилла
# ============================================================================


def backfill_exercise_identity(conn: Connection, report: BackfillReport) -> None:
    for slug, display_name, parent_slug, sort_order, is_service in sorted(
        CATEGORY_SEEDS, key=lambda s: (s[2] is not None, s[3]),
    ):
        inserted = conn.execute(
            sa.text(
                "INSERT INTO exercise_categories (slug, display_name, parent_id, sort_order, is_service) "
                "VALUES (:slug, :display_name, (SELECT id FROM exercise_categories WHERE slug = :parent), "
                ":sort_order, :is_service) ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": slug, "display_name": display_name, "parent": parent_slug,
                "sort_order": sort_order, "is_service": is_service,
            },
        )
        report.categories_inserted += inserted.rowcount

    report.exercises_display_name += conn.execute(
        sa.text("UPDATE exercises SET display_name = name WHERE display_name IS NULL"),
    ).rowcount

    report.unknown_categories = sorted(
        row[0] for row in conn.execute(
            sa.text("SELECT DISTINCT category FROM exercises WHERE category_id IS NULL AND NOT (category = ANY(:known))"),
            {"known": list(LEGACY_CATEGORY_TO_SLUG)},
        )
    )
    for legacy, slug in sorted(LEGACY_CATEGORY_TO_SLUG.items()):
        report.exercises_category += conn.execute(
            sa.text(
                "UPDATE exercises SET category_id = (SELECT id FROM exercise_categories WHERE slug = :slug) "
                "WHERE category_id IS NULL AND category = :legacy"
            ),
            {"slug": slug, "legacy": legacy},
        ).rowcount
    report.exercises_category += conn.execute(
        sa.text(
            "UPDATE exercises SET category_id = (SELECT id FROM exercise_categories WHERE slug = :slug) "
            "WHERE category_id IS NULL"
        ),
        {"slug": CATEGORY_UNCATEGORIZED},
    ).rowcount
    for legacy, slug in sorted(LEGACY_SUBCATEGORY_TO_SLUG.items()):
        report.exercises_subcategory += conn.execute(
            sa.text(
                "UPDATE exercises SET subcategory_id = (SELECT id FROM exercise_categories WHERE slug = :slug) "
                "WHERE subcategory_id IS NULL AND subcategory = :legacy"
            ),
            {"slug": slug, "legacy": legacy},
        ).rowcount

    report.exercises_visibility += conn.execute(
        sa.text(
            "UPDATE exercises SET visibility = CASE "
            "WHEN owner_user_id IS NOT NULL THEN 'user' "
            "WHEN subcategory = ANY(:roles) OR subcategory LIKE 'elective\\_%' THEN 'internal' "
            "ELSE 'public' END WHERE visibility IS NULL"
        ),
        {"roles": list(ROLE_SUBCATEGORIES)},
    ).rowcount

    canonical = conn.execute(
        sa.text(
            "SELECT id FROM exercises WHERE name = :name AND owner_user_id IS NULL AND subcategory IS NULL "
            "ORDER BY id LIMIT 1"
        ),
        {"name": CANONICAL_PULL_UP_NAME},
    ).scalar()
    if canonical is not None:
        report.exercises_analytics_identity += conn.execute(
            sa.text(
                "UPDATE exercises SET analytics_exercise_id = :canonical "
                "WHERE analytics_exercise_id IS NULL AND owner_user_id IS NULL AND id <> :canonical "
                "AND category_id = (SELECT id FROM exercise_categories WHERE slug = :pull_ups) "
                "AND (subcategory = ANY(:roles) OR subcategory LIKE 'elective\\_%')"
            ),
            {"canonical": canonical, "pull_ups": CATEGORY_PULL_UPS, "roles": list(ROLE_SUBCATEGORIES)},
        ).rowcount

    for name, slug in sorted(SYSTEM_EXERCISE_SLUGS.items()):
        report.exercises_slug += conn.execute(
            sa.text(
                "UPDATE exercises SET slug = :slug WHERE id = ("
                "  SELECT id FROM exercises WHERE name = :name AND owner_user_id IS NULL ORDER BY id LIMIT 1"
                ") AND slug IS NULL AND NOT EXISTS (SELECT 1 FROM exercises WHERE slug = :slug)"
            ),
            {"slug": slug, "name": name},
        ).rowcount


def backfill_workout_definition_versions(conn: Connection, report: BackfillReport) -> None:
    """Каждой тренировке — версия из V1-головы.

    Системные: только если указателя ещё нет (дальше их ведёт reauthor_system_workouts).
    Пользовательские: голова V1 — источник правды, пока Builder пишет V1, поэтому версия
    сверяется с головой каждый прогон; голова, равная текущей версии, = 0 изменений."""
    complexes = conn.execute(
        sa.text("SELECT id, name, source_type, current_version_id FROM complexes ORDER BY id"),
    ).all()
    for row in complexes:
        if row.source_type == "system" and row.current_version_id is not None:
            continue
        try:
            stored = content_from_v1(row.name, load_v1_items(conn, row.id))
            version_id, _, created = save_version(conn, row.id, stored)
        except MappingError as exc:
            report.flagged.append(f"complex {row.id} ({row.source_type}): {exc.reason}")
            if set_current_version(conn, row.id, None):
                report.current_version_cleared += 1
            continue
        if created:
            report.versions_created += 1
        if set_current_version(conn, row.id, version_id):
            report.current_version_set += 1


def reauthor_system_workouts(conn: Connection, report: BackfillReport) -> None:
    """Переписанная версия добавляется поверх текущей, только если текущая — ещё механическое
    отображение сидовой V1-головы (или её нет). Уже переписанная — 0 изменений; любая другая
    (владелец сохранил своё) — не трогаем и сообщаем."""
    for title, seeded_protocol in SEEDED_V1_PROTOCOLS.items():
        complex_row = conn.execute(
            sa.text(
                "SELECT id FROM complexes WHERE name = :name AND source_type = 'system' "
                "AND owner_user_id IS NULL ORDER BY id LIMIT 1"
            ),
            {"name": title},
        ).first()
        if complex_row is None:
            continue
        items = load_v1_items(conn, complex_row.id)
        if len(items) != 1 or items[0].protocol != seeded_protocol:
            report.flagged.append(f"system workout {title!r} (complex {complex_row.id}): head differs from seed, not re-authored")
            continue
        content = reauthored_system_content(title, item_id=items[0].item_id, exercise_id=items[0].exercise_id)
        assert content is not None
        digest = content_hash(content)
        current = _current_version(conn, complex_row.id)
        if current is not None and current.content_hash == digest:
            continue
        if current is not None and current.content_hash != content_hash(content_from_v1(title, items)):
            report.flagged.append(
                f"system workout {title!r} (complex {complex_row.id}): current version is neither the seeded head "
                "nor the re-authored content, not re-authored",
            )
            continue
        version_id, version_no, created = save_version(conn, complex_row.id, content)
        if created:
            report.versions_created += 1
            report.reauthored.append(f"{title} → v{version_no}")
        if set_current_version(conn, complex_row.id, version_id):
            report.current_version_set += 1


def run_backfill(conn: Connection) -> BackfillReport:
    report = BackfillReport()
    backfill_exercise_identity(conn, report)
    backfill_workout_definition_versions(conn, report)
    reauthor_system_workouts(conn, report)
    return report


def report_lines(report: BackfillReport) -> list[str]:
    data: dict[str, int] = {
        "categories_inserted": report.categories_inserted,
        "exercises_display_name": report.exercises_display_name,
        "exercises_category": report.exercises_category,
        "exercises_subcategory": report.exercises_subcategory,
        "exercises_visibility": report.exercises_visibility,
        "exercises_analytics_identity": report.exercises_analytics_identity,
        "exercises_slug": report.exercises_slug,
        "versions_created": report.versions_created,
        "current_version_set": report.current_version_set,
        "current_version_cleared": report.current_version_cleared,
        "total_changes": report.total_changes,
    }
    lines = [f"{key}: {value}" for key, value in data.items()]
    lines += [f"unknown category: {c!r}" for c in report.unknown_categories]
    lines += [f"reauthored: {r}" for r in report.reauthored]
    lines += [f"flagged: {f}" for f in report.flagged]
    return lines
