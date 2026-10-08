"""Замороженный бэкфилл ревизии b7d2e9f4a1c3 (issue #303, review B2).

1. Чистота: помощник импортирует только stdlib + SQLAlchemy, ревизия — только помощник.
2. Golden: буквальные SHA-256 системного контента, который пишет ЭТА ревизия. Эти литералы не
   правятся никогда — даже если рантайм-семантика позже намеренно изменится (тогда меняется/
   удаляется parity-тест ниже, а не golden). Два из них сверены вне кода проекта: канонический
   JSON выписан руками и прогнан через `sha256sum`.
3. Parity: НА СЕГОДНЯ замороженная логика ≡ рантайм на всех векторах миграции (фиксированные
   повторения, лесенка, максимум, время, интервалы, системные тренировки, «старые» V1-строки,
   неоднозначные/невалидные случаи — одинаково отклоняются).
4. Адверсариальная проба: подмена рантайм-умолчаний/ключа/сериализатора меняет рантайм, но не
   вывод замороженной логики.
"""

import ast
from dataclasses import astuple
from decimal import Decimal
from pathlib import Path

import pytest

from app.db.migrations._frozen import b7d2e9f4a1c3_backfill as frozen
from app.domain import exercise_identity
from app.domain import workout_definition as wd
from app.domain.electives import MAX_REPS_LADDER_REST_SECONDS, W_LADDER
from app.domain.electives import W_LADDER_REST_SECONDS as ELECTIVE_W_REST

REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_PATH = REPO_ROOT / "app/db/migrations/_frozen/b7d2e9f4a1c3_backfill.py"
REVISION_PATH = REPO_ROOT / "app/db/migrations/versions/b7d2e9f4a1c3_workout_definition_v2.py"

# Идентификаторы свежей установки (сид a4c8e1f7b2d9): строки complex_items 1–4, упражнение
# «Подтягивания — факультатив…» = 7 у всех четырёх. Те же хеши проверяет
# test_workout_definition_migration.py::test_fresh_db_golden_hashes на реальной миграции.
FRESH_EXERCISE_ID = 7
FRESH_ITEM_IDS = {"Максимум подтягиваний": 1, "W-лесенка": 2, "3 минуты подтягиваний": 3, "Объём ×5": 4}

GOLDEN_CURRENT = {
    "Максимум подтягиваний": "8a9ec1d5bad7ef4ab923aef4db309b3eaf548510d9ef2e05923d5146fdebb496",
    "W-лесенка": "9cb44e16a2e25436dad353c06f43683606bd574bcf403d1455c42941bfe0260c",
    "3 минуты подтягиваний": "caa4b52e8d6b306178c6dce776ba84472a5227b856b5b59a1976ca0387d3c2ba",
    "Объём ×5": "18bab47c70e485ffb3b518a282dec520d64f4f30d744b707de75133488b3b2fb",
}
GOLDEN_V1 = {  # version 1 = механическое V1 → v2 сидовой головы
    "Максимум подтягиваний": "ac4e434af18a666eb50eb597d86cdd87fd54a0609da15eb2f415f684f176efda",
    "W-лесенка": "80c4d49cb571627ca097032114f5dba1cd2e184fa13661943b35c185e0e6d766",
    "3 минуты подтягиваний": "45c17fc87d42db44a78a448962b4a0a6013fc2aebd0c02c5b34d5afce2b1f0d2",
    "Объём ×5": "18bab47c70e485ffb3b518a282dec520d64f4f30d744b707de75133488b3b2fb",
}
SEEDED_HEADS = {
    **frozen.SEEDED_V1_PROTOCOLS,
    "Объём ×5": {"type": "reps_sets", "prescription": {"source": "static", "sets": 5, "reps": 8}, "rest_seconds": 120},
}


def _frozen_v1_head(title: str) -> dict:
    item = frozen.V1Item(
        item_id=FRESH_ITEM_IDS[title], exercise_id=FRESH_EXERCISE_ID, order_index=0, protocol=SEEDED_HEADS[title],
    )
    return frozen.content_from_v1(title, [item])


def _frozen_current(title: str) -> dict:
    reauthored = frozen.reauthored_system_content(
        title, item_id=FRESH_ITEM_IDS[title], exercise_id=FRESH_EXERCISE_ID,
    )
    return reauthored if reauthored is not None else _frozen_v1_head(title)


# --- 1. Чистота импортов -------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    return modules


def test_frozen_helper_imports_only_stdlib_and_sqlalchemy():
    allowed_stdlib = {"hashlib", "json", "collections.abc", "dataclasses", "decimal", "typing"}
    for module in _imported_modules(FROZEN_PATH):
        assert module in allowed_stdlib or module == "sqlalchemy" or module.startswith("sqlalchemy."), module


def test_revision_imports_frozen_helper_not_runtime_code():
    app_imports = {m for m in _imported_modules(REVISION_PATH) if m.startswith("app")}
    assert app_imports == {"app.db.migrations._frozen.b7d2e9f4a1c3_backfill"}


# --- 2. Golden-хеши (буквальные, не вычисляемые) -----------------------------------------------------


@pytest.mark.parametrize("title", sorted(GOLDEN_CURRENT))
def test_golden_hash_of_current_system_content(title):
    assert frozen.content_hash(_frozen_current(title)) == GOLDEN_CURRENT[title]


@pytest.mark.parametrize("title", sorted(GOLDEN_V1))
def test_golden_hash_of_v1_mapped_seed_head(title):
    assert frozen.content_hash(_frozen_v1_head(title)) == GOLDEN_V1[title]


def test_golden_contents_spell_the_reauthored_prescriptions():
    ladder = _frozen_current("W-лесенка")["blocks"][0]
    assert [s["target_reps"] for s in ladder["sets"]] == [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5]
    assert [s["rest_after_seconds"] for s in ladder["sets"]] == [10] * 16 + [None]
    maximum = _frozen_current("Максимум подтягиваний")["blocks"][0]
    assert [(s["kind"], s["target_reps"], s["rest_after_seconds"]) for s in maximum["sets"]] == [
        ("max_reps", None, 180), ("max_reps", None, 120), ("max_reps", None, 60), ("max_reps", None, None),
    ]
    assert _frozen_current("3 минуты подтягиваний")["blocks"][0]["interval"] == {
        "work_seconds": 10, "rest_seconds": 20, "rounds": 6, "record_reps_per_round": True,
    }
    assert ladder["key"] == "i2e7"


# --- 3. Parity на сегодня -----------------------------------------------------------------------------

R = {"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 10}, "rest_seconds": 90}


def _reps(sets, reps, **extra):
    return {"type": "reps_sets", "prescription": {"source": "static", "sets": sets, "reps": reps}, **extra}


def _interval(total, work, rest):
    return {"type": "interval", "total_duration_seconds": total, "work_seconds": work, "rest_seconds": rest,
            "starts_with": "work"}


# (title, [(item_id, exercise_id, order_index, protocol, legacy kwargs, progression_role)])
VECTORS: dict[str, tuple[str, list[tuple]]] = {
    "fixed_reps": ("Моя 3×10", [(7001, 5001, 0, R, {}, None)]),
    "ladder_v1_head": ("W-лесенка", [(2, 7, 0, SEEDED_HEADS["W-лесенка"], {}, None)]),
    "max_seed": ("Максимум подтягиваний", [(1, 7, 0, SEEDED_HEADS["Максимум подтягиваний"], {}, None)]),
    "max_without_rest": ("Макс", [(1, 3, 0, {"type": "max_effort", "prescription": {"source": "static", "attempts": 2}}, {}, None)]),
    "timed": ("Планка", [(5, 2, 0, {"type": "time_sets", "prescription": {"source": "static", "sets": 2, "duration_seconds": 30},
                                     "rest_seconds": 60}, {}, None)]),
    "interval_seed": ("3 минуты подтягиваний", [(3, 7, 0, SEEDED_HEADS["3 минуты подтягиваний"], {}, None)]),
    "interval_not_divisible": ("Кривой", [(7004, 5001, 0, _interval(100, 10, 20), {}, None)]),
    "interval_zero_total": ("И", [(1, 1, 0, _interval(0, 10, 20), {}, None)]),
    "interval_zero_work": ("И", [(1, 1, 0, _interval(60, 0, 20), {}, None)]),
    "interval_negative_rest": ("И", [(1, 1, 0, _interval(90, 40, -10), {}, None)]),
    "volume_seed": ("Объём ×5", [(4, 7, 0, SEEDED_HEADS["Объём ×5"], {}, None)]),
    "aged_plank_plus_max": ("Планка + макс", [
        (7002, 9, 0, {"type": "time_sets", "prescription": {"source": "static", "sets": 2, "duration_seconds": 30},
                      "rest_seconds": 60}, {}, None),
        (7003, 5001, 1, {"type": "max_effort", "prescription": {"source": "static", "attempts": 2}}, {}, None),
    ]),
    "aged_archived_single": ("Архивная", [(7006, 5001, 0, _reps(1, 5, rest_seconds=0), {}, None)]),
    "aged_legacy_reps": ("Legacy", [(7005, 5001, 0, None, {"sets": 4, "target_value": Decimal(6), "target_unit": "reps",
                                                          "rest_seconds": 45}, None)]),
    "legacy_seconds_no_rest": ("L", [(1, 1, 0, None, {"sets": 2, "target_value": Decimal("30.00"), "target_unit": "s"}, None)]),
    "legacy_fractional": ("L", [(1, 1, 0, None, {"sets": 3, "target_value": Decimal("2.5"), "target_unit": "reps"}, None)]),
    "legacy_kg": ("L", [(1, 1, 0, None, {"sets": 3, "target_value": Decimal(5), "target_unit": "kg"}, None)]),
    "legacy_zero_sets": ("L", [(1, 1, 0, None, {"sets": 0, "target_value": Decimal(5), "target_unit": "reps"}, None)]),
    "legacy_negative_rest": ("L", [(1, 1, 0, None, {"sets": 2, "target_value": Decimal(5), "target_unit": "reps",
                                                    "rest_seconds": -5}, None)]),
    "legacy_reps_too_big": ("L", [(1, 1, 0, None, {"sets": 2, "target_value": Decimal(1000), "target_unit": "reps"}, None)]),
    "progression_block_a": ("Курс", [(1, 2, 0, {"type": "reps_sets", "prescription": {"source": "progression"},
                                                "rest_seconds": 180}, {}, "block_a")]),
    "progression_without_role": ("Курс", [(1, 2, 0, {"type": "reps_sets", "prescription": {"source": "progression"}}, {}, None)]),
    "progression_second_block": ("Курс", [
        (1, 2, 0, R, {}, None),
        (2, 3, 1, {"type": "reps_sets", "prescription": {"source": "progression"}}, {}, "block_b"),
    ]),
    "rest_null_defaults": ("R", [(1, 1, 0, _reps(3, 5, rest_seconds=None), {}, None)]),
    "rest_missing_is_zero": ("R", [(1, 1, 0, _reps(3, 5), {}, None)]),
    "rest_junk_single_set": ("R", [(1, 1, 0, _reps(1, 5, rest_seconds="x"), {}, None)]),
    "rest_junk_two_sets": ("R", [(1, 1, 0, _reps(2, 5, rest_seconds="x"), {}, None)]),
    "rest_bool": ("R", [(1, 1, 0, _reps(2, 5, rest_seconds=True), {}, None)]),
    "rest_too_big": ("R", [(1, 1, 0, _reps(2, 5, rest_seconds=86_401), {}, None)]),
    "sets_zero": ("R", [(1, 1, 0, _reps(0, 5), {}, None)]),
    "sets_too_many": ("R", [(1, 1, 0, _reps(101, 5), {}, None)]),
    "sets_max": ("R", [(1, 1, 0, _reps(100, 5), {}, None)]),
    "sets_bool": ("R", [(1, 1, 0, _reps(True, 5), {}, None)]),
    "reps_zero": ("R", [(1, 1, 0, _reps(3, 0), {}, None)]),
    "reps_too_big": ("R", [(1, 1, 0, _reps(3, 1000), {}, None)]),
    "reps_bool": ("R", [(1, 1, 0, _reps(3, True), {}, None)]),
    "reps_float": ("R", [(1, 1, 0, _reps(3, 10.0), {}, None)]),
    "unknown_type": ("R", [(1, 1, 0, {"type": "ladder"}, {}, None)]),
    "empty_protocol": ("R", [(1, 1, 0, {}, {}, None)]),
    "protocol_not_object": ("R", [(1, 1, 0, ["reps_sets"], {}, None)]),
    "prescription_not_object": ("R", [(1, 1, 0, {"type": "reps_sets", "prescription": "3x10"}, {}, None)]),
    "weird_source": ("R", [(1, 1, 0, {"type": "reps_sets", "prescription": {"source": "coach", "sets": 1, "reps": 1}}, {}, None)]),
    "time_progression": ("R", [(1, 1, 0, {"type": "time_sets", "prescription": {"source": "progression"}}, {}, None)]),
    "empty_workout": ("Пустая", []),
    "blank_title": ("   ", [(1, 1, 0, R, {}, None)]),
    "padded_title": ("  Тренировка  ", [(1, 1, 0, R, {}, None)]),
    "long_title": ("Т" * 256, [(1, 1, 0, R, {}, None)]),
    "order_then_id": ("O", [(9, 1, 1, R, {}, None), (3, 2, 0, _reps(1, 1), {}, None), (5, 1, 1, _reps(2, 2), {}, None)]),
    "fifty_blocks": ("B", [(i, 1, i, _reps(1, 1), {}, None) for i in range(1, 51)]),
    "fifty_one_blocks": ("B", [(i, 1, i, _reps(1, 1), {}, None) for i in range(1, 52)]),
    "time_first_in_second_block": ("P", [
        (1, 1, 0, R, {}, None),
        (2, 2, 1, {"type": "time_sets", "prescription": {"source": "static", "sets": 1, "duration_seconds": 20}}, {}, None),
        (3, 3, 2, {"type": "max_effort", "prescription": {"source": "static", "attempts": 1}}, {}, None),
    ]),
}


def _items(module, rows):
    return [
        module.V1Item(item_id=i, exercise_id=e, order_index=o, protocol=p, progression_role=role, **legacy)
        for i, e, o, p, legacy, role in rows
    ]


@pytest.mark.parametrize("name", sorted(VECTORS))
def test_frozen_v1_mapping_equals_runtime_today(name):
    title, rows = VECTORS[name]
    try:
        runtime = wd.content_from_v1(title, _items(wd, rows))
    except wd.V1MappingError:
        runtime = None
    try:
        stored = frozen.content_from_v1(title, _items(frozen, rows))
    except frozen.MappingError:
        stored = None
    assert (runtime is None) == (stored is None), (name, runtime, stored)
    if runtime is not None:
        assert stored == wd.to_dict(runtime)
        assert frozen.content_hash(stored) == wd.content_hash(runtime)
        assert frozen.canonical_json(stored) == wd.canonical_json(runtime)
        assert wd.content_from_stored(stored, expected_hash=frozen.content_hash(stored)) == runtime


def test_parity_vectors_cover_both_outcomes():
    outcomes = set()
    for title, rows in VECTORS.values():
        try:
            frozen.content_from_v1(title, _items(frozen, rows))
            outcomes.add("ok")
        except frozen.MappingError:
            outcomes.add("flagged")
    assert outcomes == {"ok", "flagged"}


@pytest.mark.parametrize("title", sorted(frozen.SEEDED_V1_PROTOCOLS))
def test_frozen_reauthored_system_content_equals_runtime_today(title):
    stored = frozen.reauthored_system_content(title, item_id=11, exercise_id=22)
    assert stored is not None
    # Рантайм: тот же рецепт, записанный «как автор» (сокращения и умолчания — дело normalize()).
    key = wd.v1_block_key(11, 22)
    if title == "W-лесенка":
        sets = [{"kind": "reps", "target_reps": r, "rest_after_seconds": ELECTIVE_W_REST} for r in W_LADDER]
        del sets[-1]["rest_after_seconds"]
        raw_block = {"key": key, "exercise_id": 22, "sets": sets}
    elif title == "Максимум подтягиваний":
        rests = [*MAX_REPS_LADDER_REST_SECONDS, None]
        raw_block = {"key": key, "exercise_id": 22, "sets": [{"kind": "max_reps", "rest_after_seconds": r} for r in rests]}
    else:
        raw_block = {"key": key, "exercise_id": 22, "interval": {
            "work_seconds": 10, "rest_seconds": 20, "rounds": 6, "record_reps_per_round": True,
        }}
    runtime = wd.normalize({"title": title, "blocks": [raw_block]})
    assert stored == wd.to_dict(runtime)
    assert frozen.content_hash(stored) == wd.content_hash(runtime)
    assert wd.normalize(stored) == runtime  # замороженная форма — неподвижная точка рантайм-normalize


def test_frozen_literals_equal_runtime_constants_today():
    assert frozen.W_LADDER_TARGETS == tuple(W_LADDER)
    assert frozen.W_LADDER_REST_SECONDS == ELECTIVE_W_REST
    assert frozen.MAX_LADDER_RESTS == tuple(MAX_REPS_LADDER_REST_SECONDS)
    assert frozen.CATEGORY_SEEDS == tuple(astuple(seed) for seed in exercise_identity.CATEGORY_SEEDS)
    assert frozen.LEGACY_CATEGORY_TO_SLUG == exercise_identity.LEGACY_CATEGORY_TO_SLUG
    assert frozen.LEGACY_SUBCATEGORY_TO_SLUG == exercise_identity.LEGACY_SUBCATEGORY_TO_SLUG
    assert frozen.SYSTEM_EXERCISE_SLUGS == exercise_identity.SYSTEM_EXERCISE_SLUGS
    assert (frozen.CATEGORY_PULL_UPS, frozen.CATEGORY_MY_EXERCISES, frozen.CATEGORY_UNCATEGORIZED) == (
        exercise_identity.CATEGORY_PULL_UPS, exercise_identity.CATEGORY_MY_EXERCISES,
        exercise_identity.CATEGORY_UNCATEGORIZED,
    )
    assert (frozen.DEFAULT_REST_SECONDS, frozen.DEFAULT_PREP_SECONDS, frozen.SCHEMA_VERSION) == (
        wd.SYSTEM_DEFAULT_REST_SECONDS, wd.DEFAULT_PREP_SECONDS, wd.SCHEMA_VERSION,
    )
    assert (frozen.MAX_SETS_PER_BLOCK, frozen.MAX_BLOCKS, frozen.MAX_TARGET_REPS, frozen.MAX_SECONDS,
            frozen.MAX_INTERVAL_ROUNDS, frozen.MAX_TITLE_LENGTH) == (
        wd.MAX_SETS_PER_BLOCK, wd.MAX_BLOCKS, wd.MAX_TARGET_REPS, wd.MAX_SECONDS,
        wd.MAX_INTERVAL_ROUNDS, wd.MAX_TITLE_LENGTH,
    )


# --- 4. Адверсариальная проба: рантайм меняется — замороженная ревизия нет ------------------------------


def test_changing_runtime_semantics_does_not_change_frozen_migration_output(monkeypatch):
    probe_title, probe_rows = VECTORS["aged_plank_plus_max"]
    frozen_before = frozen.content_from_v1(probe_title, _items(frozen, probe_rows))
    runtime_before = wd.content_hash(wd.content_from_v1(probe_title, _items(wd, probe_rows)))

    monkeypatch.setattr(wd, "SYSTEM_DEFAULT_REST_SECONDS", 60)
    monkeypatch.setattr(wd, "DEFAULT_PREP_SECONDS", 3)
    monkeypatch.setattr(wd, "v1_block_key", lambda item_id, exercise_id: f"block-{item_id}")
    monkeypatch.setitem(wd._STORED_CANONICAL_JSON, 2, lambda stored: "changed:" + frozen.canonical_json(stored))
    monkeypatch.setattr(exercise_identity, "CATEGORY_SEEDS", ())
    monkeypatch.setattr(exercise_identity, "SYSTEM_EXERCISE_SLUGS", {})

    # проба действительно меняет рантайм…
    runtime_after = wd.content_from_v1(probe_title, _items(wd, probe_rows))
    assert wd.content_hash(runtime_after) != runtime_before
    assert runtime_after.blocks[0].key == "block-7002" and runtime_after.blocks[0].prep_seconds == 3
    # …а вывод ревизии b7d2e9f4a1c3 — нет
    assert frozen.content_from_v1(probe_title, _items(frozen, probe_rows)) == frozen_before
    for title, golden in GOLDEN_CURRENT.items():
        assert frozen.content_hash(_frozen_current(title)) == golden
        assert frozen.content_hash(_frozen_v1_head(title)) == GOLDEN_V1[title]
    assert len(frozen.CATEGORY_SEEDS) == 11 and len(frozen.SYSTEM_EXERCISE_SLUGS) == 14
