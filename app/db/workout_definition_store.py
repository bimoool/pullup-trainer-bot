"""WorkoutDefinition v2: запись версий рантаймом (issue #303).

Единственная реализация «сохранить версию» для рантайма: WorkoutDefinitionRepository вызывает
её через AsyncSession.run_sync (номер версии, блокировка, W5 по всей истории — один раз).

Миграция b7d2e9f4a1c3 этот модуль НЕ импортирует: у неё своя замороженная копия
(app/db/migrations/_frozen/b7d2e9f4a1c3_backfill.py, WORKOUT_DOMAIN_V2 §9.10) — изменение
рантайм-семантики не меняет того, что пишет старая ревизия.

Версии append-only и монотонны (WORKOUT_DOMAIN_V2 §5, решение владельца B1): no-op — только
если новое нормализованное содержимое совпадает с ТЕКУЩЕЙ версией; иначе version_no =
max + 1, указатель двигается только вперёд на новую голову.
"""

import json
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.domain.workout_definition import (
    V1Item,
    V1MappingError,
    WorkoutContent,
    WorkoutContentError,
    assert_block_keys_stable,
    content_from_v1,
    content_hash,
    to_dict,
)

_ROLE_SUBCATEGORIES = ("block_a", "block_b")


def _json(value: Any) -> Any:
    # sa.text() без типов колонок: драйвер может вернуть JSONB строкой.
    return json.loads(value) if isinstance(value, str) else value


def block_key_history(conn: Connection, workout_definition_id: int) -> list[tuple[str, int]]:
    """(key, exercise_id) блоков ВСЕХ версий определения — из хранимого JSON как есть (W5)."""
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT b.value ->> 'key' AS key, (b.value ->> 'exercise_id')::bigint AS exercise_id "
            "FROM workout_definition_versions v "
            "CROSS JOIN LATERAL jsonb_array_elements(v.content -> 'blocks') AS b(value) "
            "WHERE v.workout_definition_id = :id"
        ),
        {"id": workout_definition_id},
    ).all()
    return [(row.key, row.exercise_id) for row in rows]


def save_version(conn: Connection, workout_definition_id: int, content: WorkoutContent) -> tuple[int, int, bool]:
    """(version_id, version_no, created).

    Содержимое = текущей версии (complexes.current_version_id) — ничего не создаётся. Любое
    другое — новая строка version_no = max + 1, даже если такое же содержимое было в более
    старой версии (A → B → A = v1, v2, v3). Перед вставкой — W5 по ключам всех прежних версий.
    Строка complexes блокируется FOR UPDATE — два параллельных сохранения не получат один номер."""
    digest = content_hash(content)
    conn.execute(sa.text("SELECT id FROM complexes WHERE id = :id FOR UPDATE"), {"id": workout_definition_id})
    current = conn.execute(
        sa.text(
            "SELECT v.id, v.version_no, v.content_hash FROM complexes c "
            "JOIN workout_definition_versions v ON v.id = c.current_version_id WHERE c.id = :id"
        ),
        {"id": workout_definition_id},
    ).first()
    if current is not None and current.content_hash == digest:
        return current.id, current.version_no, False
    assert_block_keys_stable(block_key_history(conn, workout_definition_id), content)
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
            "id": workout_definition_id, "no": next_no, "schema": content.schema_version,
            "content": json.dumps(to_dict(content), ensure_ascii=False), "hash": digest,
        },
    ).scalar_one()
    return row, next_no, True


def set_current_version(conn: Connection, workout_definition_id: int, version_id: int | None) -> bool:
    """True — указатель изменился."""
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
            progression_role=row.subcategory if row.subcategory in _ROLE_SUBCATEGORIES else None,
        )
        for row in rows
    ]


def sync_from_v1_head(conn: Connection, workout_definition_id: int, title: str) -> tuple[int | None, bool, str | None]:
    """V1-голова (complex_items) → версия v2 → current_version_id.

    Возвращает (version_id | None, created, причина пропуска | None). Пустая/неоднозначная
    голова — версии нет, указатель сбрасывается (Detail не покажет устаревший рецепт)."""
    try:
        content = content_from_v1(title, load_v1_items(conn, workout_definition_id))
        version_id, _, created = save_version(conn, workout_definition_id, content)
    except (V1MappingError, WorkoutContentError) as exc:
        set_current_version(conn, workout_definition_id, None)
        return None, False, exc.reason if isinstance(exc, V1MappingError) else str(exc)
    set_current_version(conn, workout_definition_id, version_id)
    return version_id, created, None
