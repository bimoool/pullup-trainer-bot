"""WorkoutDefinition v2: сохранение версий и детерминированный бэкфилл (issue #303).

Один модуль на три вызывающих: миграция b7d2e9f4a1c3 (свежая установка и прод получают версии
сразу при `alembic upgrade head` — деплой не запускает отдельных скриптов),
scripts/backfill_workout_definition_v2.py (`--dry-run` с отчётом, повторный прогон) и
WorkoutDefinitionRepository (через AsyncSession.run_sync) — так «сохранить версию» реализовано
ровно один раз (UNIQUE-ключи, номер версии, блокировка), без второй копии логики.

Отступление от конвенции «миграция не импортирует живой код» (a4c8e1f7b2d9 копирует константы
литералами) — осознанное: V1 → v2 и канонический хеш должны быть ОДНОЙ функцией с рантаймом,
иначе версия из бэкфилла и версия из API для одного и того же содержимого получили бы разные
хеши. Модуль импортирует только чистый домен (app.domain.*) и sqlalchemy — ни конфиг, ни
модели. Переписанный системный контент (§8 брифа) — замороженные литералы ниже.

MIGRATION_V2 §3: порядок ORDER BY id, натуральные ключи, ON CONFLICT DO NOTHING, повторный
прогон = 0 изменений. Не трогает подписки, доступ, планы, включения, сессии и историю.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.domain.exercise_identity import (
    CATEGORY_PULL_UPS,
    CATEGORY_SEEDS,
    CATEGORY_UNCATEGORIZED,
    LEGACY_CATEGORY_TO_SLUG,
    LEGACY_SUBCATEGORY_TO_SLUG,
    SYSTEM_EXERCISE_SLUGS,
)
from app.domain.workout_definition import (
    V1Item,
    V1MappingError,
    WorkoutContent,
    content_from_v1,
    content_hash,
    normalize,
    to_dict,
    v1_block_key,
)

_ROLE_SUBCATEGORIES = ("block_a", "block_b")
_CANONICAL_PULL_UP_NAME = "Подтягивания"


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
    # sa.text() без типов колонок: драйвер может вернуть JSONB строкой.
    return json.loads(value) if isinstance(value, str) else value


# ============================================================================
# Версии
# ============================================================================


def save_version(conn: Connection, workout_definition_id: int, content: WorkoutContent) -> tuple[int, int, bool]:
    """Идемпотентное сохранение: (version_id, version_no, created).

    Тот же нормализованный хеш, что у уже существующей версии этого определения, — новая
    версия не создаётся (UNIQUE (definition, hash)); иначе version_no = max + 1. Строка
    complexes блокируется FOR UPDATE — два параллельных сохранения не получат один номер."""
    digest = content_hash(content)
    conn.execute(sa.text("SELECT id FROM complexes WHERE id = :id FOR UPDATE"), {"id": workout_definition_id})
    existing = conn.execute(
        sa.text(
            "SELECT id, version_no FROM workout_definition_versions "
            "WHERE workout_definition_id = :id AND content_hash = :hash"
        ),
        {"id": workout_definition_id, "hash": digest},
    ).first()
    if existing is not None:
        return existing.id, existing.version_no, False
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
    except V1MappingError as exc:
        set_current_version(conn, workout_definition_id, None)
        return None, False, exc.reason
    version_id, _, created = save_version(conn, workout_definition_id, content)
    set_current_version(conn, workout_definition_id, version_id)
    return version_id, created, None


# ============================================================================
# Переписанный системный контент (замороженные литералы)
# ============================================================================

# Голова V1, которую положил сид a4c8e1f7b2d9. Переписываем, только если голова в точности такая
# (владелец мог отредактировать системную тренировку — тогда не угадываем, а сообщаем).
_SEEDED_V1_PROTOCOLS: dict[str, dict[str, Any]] = {
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

# app.domain.electives на 2026-10-08: W_LADDER, W_LADDER_REST_SECONDS, MAX_REPS_LADDER_SETS,
# MAX_REPS_LADDER_REST_SECONDS, THREE_MINUTES_* — копия значений, сверяется тестом.
W_LADDER_TARGETS: tuple[int, ...] = (5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5)
W_LADDER_REST_SECONDS = 10
MAX_LADDER_RESTS: tuple[int, ...] = (180, 120, 60)


def _with_rests(sets: list[dict[str, Any]], rests: list[int]) -> list[dict[str, Any]]:
    return [{**s, "rest_after_seconds": rests[i]} if i < len(sets) - 1 else s for i, s in enumerate(sets)]


def reauthored_system_content(title: str, *, item_id: int, exercise_id: int) -> WorkoutContent | None:
    """v2-рецепт системной тренировки (issue #303 §8 брифа) или None — не из списка."""
    block: dict[str, Any] = {"key": v1_block_key(item_id), "exercise_id": exercise_id}
    if title == "W-лесенка":
        sets = [{"kind": "reps", "target_reps": r} for r in W_LADDER_TARGETS]
        block["sets"] = _with_rests(sets, [W_LADDER_REST_SECONDS] * (len(sets) - 1))
    elif title == "Максимум подтягиваний":
        block["sets"] = _with_rests([{"kind": "max_reps"} for _ in range(4)], list(MAX_LADDER_RESTS))
    elif title == "3 минуты подтягиваний":
        block["kind"] = "interval"
        block["interval"] = {"work_seconds": 10, "rest_seconds": 20, "rounds": 6, "record_reps_per_round": True}
    else:
        return None
    return normalize({"title": title, "blocks": [block]})


def reauthor_system_workouts(conn: Connection, report: BackfillReport) -> None:
    for title, seeded_protocol in _SEEDED_V1_PROTOCOLS.items():
        complex_row = conn.execute(
            sa.text(
                "SELECT id FROM complexes WHERE name = :name AND source_type = 'system' "
                "AND owner_user_id IS NULL ORDER BY id LIMIT 1"
            ),
            {"name": title},
        ).first()
        if complex_row is None:
            continue
        items = conn.execute(
            sa.text(
                "SELECT ci.id, ci.exercise_id, ci.protocol FROM complex_items ci "
                "WHERE ci.complex_id = :id ORDER BY ci.order_index, ci.id"
            ),
            {"id": complex_row.id},
        ).all()
        if len(items) != 1 or _json(items[0].protocol) != seeded_protocol:
            report.flagged.append(f"system workout {title!r} (complex {complex_row.id}): head differs from seed, not re-authored")
            continue
        content = reauthored_system_content(title, item_id=items[0].id, exercise_id=items[0].exercise_id)
        assert content is not None
        version_id, version_no, created = save_version(conn, complex_row.id, content)
        if created:
            report.versions_created += 1
            report.reauthored.append(f"{title} → v{version_no}")
        if set_current_version(conn, complex_row.id, version_id):
            report.current_version_set += 1


# ============================================================================
# Идентичность упражнений
# ============================================================================


def backfill_exercise_identity(conn: Connection, report: BackfillReport) -> None:
    for seed in sorted(CATEGORY_SEEDS, key=lambda s: (s.parent_slug is not None, s.sort_order)):
        inserted = conn.execute(
            sa.text(
                "INSERT INTO exercise_categories (slug, display_name, parent_id, sort_order, is_service) "
                "VALUES (:slug, :display_name, (SELECT id FROM exercise_categories WHERE slug = :parent), "
                ":sort_order, :is_service) ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": seed.slug, "display_name": seed.display_name, "parent": seed.parent_slug,
                "sort_order": seed.sort_order, "is_service": seed.is_service,
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
        {"roles": list(_ROLE_SUBCATEGORIES)},
    ).rowcount

    canonical = conn.execute(
        sa.text(
            "SELECT id FROM exercises WHERE name = :name AND owner_user_id IS NULL AND subcategory IS NULL "
            "ORDER BY id LIMIT 1"
        ),
        {"name": _CANONICAL_PULL_UP_NAME},
    ).scalar()
    if canonical is not None:
        report.exercises_analytics_identity += conn.execute(
            sa.text(
                "UPDATE exercises SET analytics_exercise_id = :canonical "
                "WHERE analytics_exercise_id IS NULL AND owner_user_id IS NULL AND id <> :canonical "
                "AND category_id = (SELECT id FROM exercise_categories WHERE slug = :pull_ups) "
                "AND (subcategory = ANY(:roles) OR subcategory LIKE 'elective\\_%')"
            ),
            {"canonical": canonical, "pull_ups": CATEGORY_PULL_UPS, "roles": list(_ROLE_SUBCATEGORIES)},
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


# ============================================================================
# Полный бэкфилл
# ============================================================================


def backfill_workout_definition_versions(conn: Connection, report: BackfillReport) -> None:
    """Каждой тренировке — версия из V1-головы.

    Системные: только если версии ещё нет (дальше их ведёт reauthor_system_workouts, голова V1 у
    переписанных уже не источник правды). Пользовательские: голова V1 — источник правды, пока
    Builder пишет V1 (авторинг v2 в UI — отдельная P2), поэтому версия сверяется с головой каждый
    прогон — правки, сделанные кодом без синхронизации (откат образа), догоняются; неизменная
    голова даёт тот же хеш = 0 изменений."""
    complexes = conn.execute(
        sa.text("SELECT id, name, source_type, current_version_id FROM complexes ORDER BY id"),
    ).all()
    for row in complexes:
        if row.source_type == "system" and row.current_version_id is not None:
            continue
        try:
            content = content_from_v1(row.name, load_v1_items(conn, row.id))
        except V1MappingError as exc:
            report.flagged.append(f"complex {row.id} ({row.source_type}): {exc.reason}")
            if set_current_version(conn, row.id, None):
                report.current_version_cleared += 1
            continue
        version_id, _, created = save_version(conn, row.id, content)
        if created:
            report.versions_created += 1
        if set_current_version(conn, row.id, version_id):
            report.current_version_set += 1


def run_backfill(conn: Connection) -> BackfillReport:
    report = BackfillReport()
    backfill_exercise_identity(conn, report)
    backfill_workout_definition_versions(conn, report)
    reauthor_system_workouts(conn, report)
    return report


def report_lines(report: BackfillReport) -> list[str]:
    data: Mapping[str, Any] = {
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
