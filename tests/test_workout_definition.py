"""WorkoutDefinition v2 — домен (issue #303). Каждый пример WORKOUT_DOMAIN_V2 §3.1 — тестовый
вектор с точной хранимой формой и точным выводом describe()."""

import copy
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.bot.parsing import MAX_REPS
from app.domain.exercise_identity import (
    analytics_identity,
    category_slug_for_legacy,
    exercise_display_label,
    looks_like_slug,
)
from app.domain.workout_definition import (
    MAX_TARGET_REPS,
    BlockKind,
    BlockSource,
    ExerciseInfo,
    SetKind,
    SetPrescription,
    SetRole,
    SnapshotResolutionError,
    V1Item,
    V1MappingError,
    WorkoutContentError,
    assert_block_keys_stable,
    block_key_pairs,
    build_prescription_snapshot,
    canonical_json,
    content_from_stored,
    content_from_v1,
    content_hash,
    describe,
    describe_rest,
    describe_workout,
    normalize,
    snapshot_from_dict,
    snapshot_to_dict,
    stored_content_hash,
    to_dict,
    total_target_reps,
)

W_LADDER = [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5]
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _one_block(**block) -> dict:
    return {"title": "T", "blocks": [{"key": "A", "exercise_id": 1, **block}]}


def _set_dict(kind, *, reps=None, seconds=None, rest=None, role="working", load=None) -> dict:
    return {
        "kind": kind, "target_reps": reps, "target_seconds": seconds, "load": load,
        "rest_after_seconds": rest, "role": role,
    }


# --- §3.1 test vectors ------------------------------------------------------------------


def test_fixed_reps_3x10_rest_90_is_three_explicit_sets():
    content = normalize(_one_block(sets=3, reps=10, rest_seconds=90))
    block = content.blocks[0]
    assert to_dict(content)["blocks"][0]["sets"] == [
        _set_dict("reps", reps=10, rest=90),
        _set_dict("reps", reps=10, rest=90),
        _set_dict("reps", reps=10, rest=None),
    ]
    assert describe(block) == "3 × 10"
    assert describe_rest(block) == "отдых 1:30"


def test_shorthand_and_explicit_sets_are_the_same_content_and_hash():
    shorthand = normalize(_one_block(sets=3, reps=10, rest_seconds=90))
    explicit = normalize(_one_block(sets=[
        {"kind": "reps", "target_reps": 10, "rest_after_seconds": 90},
        {"kind": "reps", "target_reps": 10, "rest_after_seconds": 90},
        {"kind": "reps", "target_reps": 10},
    ]))
    assert shorthand == explicit
    assert content_hash(shorthand) == content_hash(explicit)
    assert canonical_json(shorthand) == canonical_json(explicit)


def test_4x3_is_four_sets_and_describes_as_4x3():
    block = normalize(_one_block(sets=4, reps=3, rest_seconds=180)).blocks[0]
    assert len(block.sets) == 4
    assert [s.target_reps for s in block.sets] == [3, 3, 3, 3]
    assert describe(block) == "4 × 3"


def test_max_has_no_target_field_and_describes_as_maximum():
    block = normalize(_one_block(sets=[{"kind": "max_reps"}])).blocks[0]
    (set_,) = block.sets
    assert set_.kind is SetKind.MAX_REPS
    assert set_.target_reps is None and set_.target_seconds is None
    assert set_.role is SetRole.MAX
    assert describe(block) == "Максимум"
    assert "0" not in describe(block)


@pytest.mark.parametrize("bad", [{"target_reps": 0}, {"target_reps": 10}, {"target_seconds": 30}])
def test_max_with_any_target_is_rejected_w2(bad):
    with pytest.raises(WorkoutContentError) as exc:
        normalize(_one_block(sets=[{"kind": "max_reps", **bad}]))
    assert exc.value.code == "W2"


def test_w_ladder_is_17_explicit_sets_in_exact_order():
    sets = [{"kind": "reps", "target_reps": r, "rest_after_seconds": 10} for r in W_LADDER]
    del sets[-1]["rest_after_seconds"]
    block = normalize(_one_block(sets=sets)).blocks[0]
    assert len(block.sets) == 17
    assert [s.target_reps for s in block.sets] == W_LADDER
    assert [s.rest_after_seconds for s in block.sets] == [10] * 16 + [None]
    assert describe(block) == "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5"
    assert describe(block) != "17 × 3"
    assert total_target_reps(block) == 53
    assert describe_rest(block) == "отдых 0:10"


def test_17x3_is_not_the_w_ladder():
    ladder = [{"kind": "reps", "target_reps": r, "rest_after_seconds": 10} for r in W_LADDER]
    del ladder[-1]["rest_after_seconds"]
    w = normalize(_one_block(sets=ladder))
    flat = normalize(_one_block(sets=17, reps=3, rest_seconds=10))
    assert content_hash(w) != content_hash(flat)
    assert describe(flat.blocks[0]) == "17 × 3"
    assert total_target_reps(flat.blocks[0]) == 51


def test_timed_work_plank_2x30():
    block = normalize(_one_block(sets=2, seconds=30, rest_seconds=60)).blocks[0]
    assert to_dict(normalize(_one_block(sets=2, seconds=30, rest_seconds=60)))["blocks"][0]["sets"] == [
        _set_dict("time", seconds=30, rest=60), _set_dict("time", seconds=30, rest=None),
    ]
    assert describe(block) == "2 × 0:30"
    assert block.prep_seconds == 5


def test_interval_three_minutes():
    content = normalize(_one_block(
        kind="interval", interval={"work_seconds": 10, "rest_seconds": 20, "rounds": 6, "record_reps_per_round": True},
    ))
    block = content.blocks[0]
    assert block.kind is BlockKind.INTERVAL
    assert block.sets == ()
    assert block.interval.work_seconds == 10
    assert block.interval.rest_seconds == 20
    assert block.interval.rounds == 6
    assert block.interval.record_reps_per_round is True
    assert block.extra_sets_allowed is False
    assert describe(block) == "6 × (0:10 работа / 0:20 отдых)"
    assert to_dict(content)["blocks"][0]["interval"] == {
        "work_seconds": 10, "rest_seconds": 20, "rounds": 6, "record_reps_per_round": True,
    }


def test_multi_block_mixed_with_block_rest_and_trailing_max():
    content = normalize({
        "title": "Смешанная",
        "blocks": [
            {"key": "A", "exercise_id": 1, "rest_after_block_seconds": 900, "sets": [
                {"kind": "reps", "target_reps": 10, "rest_after_seconds": 240},
                {"kind": "reps", "target_reps": 10, "rest_after_seconds": 240},
                {"kind": "reps", "target_reps": 10, "rest_after_seconds": 240},
                {"kind": "max_reps"},
            ]},
            {"key": "B", "exercise_id": 2, "sets": 2, "seconds": 30, "rest_seconds": 60},
            {"key": "C", "exercise_id": 1, "interval": {"work_seconds": 10, "rest_seconds": 20, "rounds": 6}},
        ],
    })
    a, b, c = content.blocks
    assert describe(a) == "3 × 10 + Максимум"
    assert a.sets[-1].kind is SetKind.MAX_REPS and a.sets[-1].target_reps is None
    assert a.rest_after_block_seconds == 900
    assert b.rest_after_block_seconds == 90  # не задан → умолчание
    assert c.rest_after_block_seconds is None  # последний блок
    assert [blk.prep_seconds for blk in content.blocks] == [5, 5, 5]
    assert describe_workout(content, {1: "Подтягивания", 2: "Планка"}) == [
        "Подтягивания: 3 × 10 + Максимум · отдых 4:00",
        "Планка: 2 × 0:30 · отдых 1:00",
        "Подтягивания: 6 × (0:10 работа / 0:20 отдых)",
    ]


def test_block_b_4x3_plus_max_expressible():
    block = normalize(_one_block(sets=[
        *[{"kind": "reps", "target_reps": 3, "rest_after_seconds": 180} for _ in range(4)],
        {"kind": "max_reps"},
    ])).blocks[0]
    assert len(block.sets) == 5
    assert [s.kind for s in block.sets] == [SetKind.REPS] * 4 + [SetKind.MAX_REPS]
    assert describe(block) == "4 × 3 + Максимум"


def test_rest_per_set_block_workout_levels():
    content = normalize({"title": "T", "default_rest_seconds": 45, "blocks": [
        {"key": "A", "exercise_id": 1, "sets": [
            {"kind": "reps", "target_reps": 5, "rest_after_seconds": 30},
            {"kind": "reps", "target_reps": 5},
            {"kind": "reps", "target_reps": 5},
        ]},
        {"key": "B", "exercise_id": 1, "sets": 1, "reps": 5},
    ]})
    a, b = content.blocks
    assert [s.rest_after_seconds for s in a.sets] == [30, 45, None]
    assert a.rest_after_block_seconds == 45
    assert describe_rest(a) == "отдых 0:30 → 0:45"
    assert b.prep_seconds == 0  # не первый блок, reps — подготовка = предыдущий отдых


def test_zero_rest_is_explicit_no_rest_not_default():
    block = normalize(_one_block(sets=2, reps=5, rest_seconds=0)).blocks[0]
    assert [s.rest_after_seconds for s in block.sets] == [0, None]
    assert describe_rest(block) is None


def test_max_ladder_rest_180_120_60_survives():
    content = normalize(_one_block(sets=[
        {"kind": "max_reps", "rest_after_seconds": 180},
        {"kind": "max_reps", "rest_after_seconds": 120},
        {"kind": "max_reps", "rest_after_seconds": 60},
        {"kind": "max_reps"},
    ]))
    block = content.blocks[0]
    assert [s.rest_after_seconds for s in block.sets] == [180, 120, 60, None]
    assert describe(block) == "Максимум × 4"
    assert describe_rest(block) == "отдых 3:00 → 2:00 → 1:00"
    # и после сериализации/повторной нормализации
    again = normalize(to_dict(content))
    assert [s.rest_after_seconds for s in again.blocks[0].sets] == [180, 120, 60, None]


def test_extra_sets_allowed_metadata_default_and_explicit():
    assert normalize(_one_block(sets=1, reps=5)).blocks[0].extra_sets_allowed is True
    assert normalize(_one_block(sets=1, reps=5, extra_sets_allowed=False)).blocks[0].extra_sets_allowed is False


# --- Invariants W1–W8 -----------------------------------------------------------------


def _code(raw) -> str:
    with pytest.raises(WorkoutContentError) as exc:
        normalize(raw)
    return exc.value.code


def test_w1_no_global_sets_field():
    assert _code({"title": "T", "sets": 3, "blocks": [{"key": "A", "exercise_id": 1, "sets": 1, "reps": 1}]}) == "W1"


def test_w1_len_sets_is_count_no_default_of_one():
    block = normalize(_one_block(sets=7, reps=2)).blocks[0]
    assert len(block.sets) == 7


def test_w3_sets_and_interval_exclusive():
    assert _code(_one_block(kind="sets", sets=1, reps=1, interval={"work_seconds": 1, "rest_seconds": 0, "rounds": 1})) == "W3"
    assert _code(_one_block(kind="interval", sets=[{"kind": "max_reps"}],
                            interval={"work_seconds": 1, "rest_seconds": 0, "rounds": 1})) == "W3"
    assert _code(_one_block(kind="interval")) == "W3"


def test_w4_rest_on_last_set_rejected():
    assert _code(_one_block(sets=[{"kind": "reps", "target_reps": 5, "rest_after_seconds": 60}])) == "W4"


def test_w4_rest_after_last_block_rejected():
    assert _code(_one_block(sets=1, reps=5, rest_after_block_seconds=60)) == "W4"


def test_w5_duplicate_block_keys_rejected():
    assert _code({"title": "T", "blocks": [
        {"key": "A", "exercise_id": 1, "sets": 1, "reps": 1},
        {"key": "A", "exercise_id": 2, "sets": 1, "reps": 1},
    ]}) == "W5"


def test_w5_block_key_cannot_move_to_another_exercise_between_versions():
    old = normalize(_one_block(sets=1, reps=1))
    new = normalize({"title": "T", "blocks": [{"key": "A", "exercise_id": 2, "sets": 1, "reps": 1}]})
    with pytest.raises(WorkoutContentError) as exc:
        assert_block_keys_stable(block_key_pairs(old), new)
    assert exc.value.code == "W5"
    assert_block_keys_stable(block_key_pairs(old), normalize(_one_block(sets=3, reps=1)))  # тот же ключ — ок


def test_w5_checks_all_prior_versions_not_only_current():
    """Ключ A удалён в v2 и возвращён в v3 с другим упражнением — это коллизия с v1 (review B3)."""
    v1 = normalize({"title": "T", "blocks": [
        {"key": "A", "exercise_id": 1, "sets": 1, "reps": 1}, {"key": "B", "exercise_id": 2, "sets": 1, "reps": 1},
    ]})
    v2 = normalize({"title": "T", "blocks": [{"key": "B", "exercise_id": 2, "sets": 1, "reps": 1}]})
    history = block_key_pairs(v1) + block_key_pairs(v2)
    reused = normalize({"title": "T", "blocks": [{"key": "A", "exercise_id": 3, "sets": 1, "reps": 1}]})
    assert_block_keys_stable(block_key_pairs(v2), reused)  # против одной текущей — «можно»…
    with pytest.raises(WorkoutContentError) as exc:
        assert_block_keys_stable(history, reused)  # …против всей истории — нельзя
    assert exc.value.code == "W5"
    assert_block_keys_stable(history, normalize(_one_block(sets=2, reps=2)))  # A снова = упражнение 1 — ок


def test_w6_exercise_visibility():
    with pytest.raises(WorkoutContentError) as exc:
        normalize(_one_block(sets=1, reps=1), visible_exercise_ids={2, 3})
    assert exc.value.code == "W6"
    normalize(_one_block(sets=1, reps=1), visible_exercise_ids={1})


def test_w7_progression_block_has_no_sets_and_static_has_sets():
    assert _code(_one_block(source="progression", progression_role="block_a", sets=1, reps=3)) == "W7"
    assert _code(_one_block(source="progression")) == "W7"  # без роли
    assert _code(_one_block(sets=[])) == "W7"
    assert _code(_one_block()) == "W7"
    block = normalize(_one_block(source="progression", progression_role="block_a")).blocks[0]
    assert block.source is BlockSource.PROGRESSION and block.sets == ()
    assert describe(block) == "По программе"


def test_w8_extra_sets_never_in_definition():
    assert _code(_one_block(sets=[{"kind": "reps", "target_reps": 3, "is_extra": True}])) == "W8"


@pytest.mark.parametrize("raw", [
    _one_block(sets=1, reps=True),             # bool не число
    _one_block(sets=1, reps=0),                # цель 0 не план
    _one_block(sets=1, reps=MAX_TARGET_REPS + 1),
    _one_block(sets=0, reps=5),
    _one_block(sets=101, reps=1),
    _one_block(sets=1),                        # сокращение без reps/seconds
    _one_block(sets=1, reps=3, seconds=3),
    _one_block(sets=[{"kind": "reps"}]),       # reps без цели
    _one_block(sets=[{"kind": "time", "target_reps": 5, "target_seconds": 5}]),
    _one_block(sets=[{"kind": "jump"}]),
    _one_block(sets=1, reps=1, unexpected=1),
    {"title": " ", "blocks": [{"key": "A", "exercise_id": 1, "sets": 1, "reps": 1}]},
    {"title": "T", "blocks": []},
    _one_block(kind="interval", interval={"work_seconds": 0, "rest_seconds": 0, "rounds": 1}),
    _one_block(load={"kind": "added_kg"}, sets=1, reps=1),
    _one_block(load={"kind": "bodyweight", "value_kg": "5"}, sets=1, reps=1),
])
def test_invalid_input_rejected_explicitly(raw):
    with pytest.raises(WorkoutContentError):
        normalize(raw)


def test_max_target_reps_matches_bot_parsing_limit():
    assert MAX_TARGET_REPS == MAX_REPS


# --- Determinism / idempotency / hash ------------------------------------------------


def test_normalize_is_idempotent_and_hash_stable():
    content = normalize({"title": "  Тренировка ", "blocks": [
        {"key": "A", "exercise_id": 1, "load": {"kind": "added_kg", "value_kg": "5.0"},
         "sets": 3, "reps": 10, "rest_seconds": 90},
        {"key": "B", "exercise_id": 2, "interval": {"work_seconds": 10, "rest_seconds": 20, "rounds": 6}},
    ]})
    assert content.title == "Тренировка"
    again = normalize(to_dict(content))
    assert again == content
    assert content_hash(again) == content_hash(content)
    assert to_dict(content)["blocks"][0]["load"] == {"kind": "added_kg", "value_kg": "5", "item_id": None}
    assert describe(content.blocks[0]) == "3 × 10 · +5 кг"


def test_hash_is_known_value_for_simple_content():
    # Защита от случайной смены канонической формы: смена хеша = все версии «изменились».
    content = normalize(_one_block(sets=1, reps=1))
    assert canonical_json(content) == (
        '{"blocks":[{"exercise_id":1,"extra_sets_allowed":true,"interval":null,"key":"A","kind":"sets","load":null,'
        '"prep_seconds":5,"progression_role":null,"rest_after_block_seconds":null,"sets":[{"kind":"reps",'
        '"load":null,"rest_after_seconds":null,"role":"working","target_reps":1,"target_seconds":null}],'
        '"source":"static"}],"default_rest_seconds":null,"schema_version":2,"title":"T"}'
    )


def test_semantic_change_changes_hash():
    base = normalize(_one_block(sets=3, reps=10, rest_seconds=90))
    assert content_hash(base) != content_hash(normalize(_one_block(sets=3, reps=10, rest_seconds=60)))
    assert content_hash(base) != content_hash(normalize(_one_block(sets=4, reps=10, rest_seconds=90)))


# --- Snapshot ----------------------------------------------------------------------------

EXERCISES = {
    1: ExerciseInfo(id=1, display_name="Подтягивания", analytics_exercise_id=1, category_id=10),
    7: ExerciseInfo(id=7, display_name="Подтягивания — сила", analytics_exercise_id=1, category_id=10),
}


def test_snapshot_static_self_contained_and_roundtrips():
    ladder = [{"kind": "reps", "target_reps": r, "rest_after_seconds": 10} for r in W_LADDER]
    del ladder[-1]["rest_after_seconds"]
    content = normalize({"title": "W-лесенка", "blocks": [{"key": "i1e1", "exercise_id": 1, "sets": ladder}]})
    snapshot = build_prescription_snapshot(
        content, workout_definition_id=5, workout_definition_version_id=11, version_no=2,
        exercises=EXERCISES, resolved_at=NOW,
    )
    data = snapshot_to_dict(snapshot)
    assert data["title"] == "W-лесенка"
    assert data["version_no"] == 2
    assert data["blocks"][0]["exercise_display_name"] == "Подтягивания"
    assert [s["target_reps"] for s in data["blocks"][0]["sets"]] == W_LADDER
    assert data["provenance"]["kind"] == "static"
    restored = snapshot_from_dict(data)
    assert restored == snapshot
    assert describe(restored.blocks[0]) == "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5"


def test_snapshot_resolves_progression_with_trailing_max_and_provenance():
    content = normalize({"title": "Подтягивания", "blocks": [
        {"key": "B", "exercise_id": 7, "source": "progression", "progression_role": "block_b"},
    ]})

    def resolver(role: str):
        assert role == "block_b"
        return [
            *[SetPrescription(kind=SetKind.REPS, target_reps=3, rest_after_seconds=180) for _ in range(4)],
            SetPrescription(kind=SetKind.MAX_REPS, role=SetRole.MAX),
        ]

    snapshot = build_prescription_snapshot(
        content, workout_definition_id=1, workout_definition_version_id=2, version_no=1,
        exercises=EXERCISES, resolved_at=NOW, resolve_progression=resolver,
        program_inclusion_id=99, strategy="step", progression_state_rev=4,
    )
    (block,) = snapshot.blocks
    assert describe(block) == "4 × 3 + Максимум"
    assert block.analytics_exercise_id == 1
    data = snapshot_to_dict(snapshot)
    assert "source" not in data["blocks"][0] and "progression_role" not in data["blocks"][0]  # S3
    assert data["provenance"] == {
        "kind": "progression", "resolved_at": NOW.isoformat(), "program_inclusion_id": 99,
        "strategy": "step", "progression_state_rev": 4,
    }


def test_snapshot_rejects_resolver_with_fake_zero_target_d3():
    content = normalize(_one_block(source="progression", progression_role="block_b"))
    with pytest.raises(SnapshotResolutionError):
        build_prescription_snapshot(
            content, workout_definition_id=1, workout_definition_version_id=1,
            version_no=1, exercises=EXERCISES, resolved_at=NOW,
            resolve_progression=lambda role: [{"kind": "reps", "target_reps": 0}],
        )


def test_snapshot_requires_resolver_for_progression():
    content = normalize(_one_block(source="progression", progression_role="block_a"))
    with pytest.raises(SnapshotResolutionError):
        build_prescription_snapshot(
            content, workout_definition_id=1, workout_definition_version_id=1, version_no=1,
            exercises=EXERCISES, resolved_at=NOW,
        )


def test_old_snapshot_unaffected_by_later_definition_change():
    v1 = normalize({"title": "Старое", "blocks": [{"key": "A", "exercise_id": 1, "sets": 3, "reps": 10}]})
    snap = snapshot_to_dict(build_prescription_snapshot(
        v1, workout_definition_id=1, workout_definition_version_id=1, version_no=1,
        exercises=EXERCISES, resolved_at=NOW,
    ))
    frozen = copy.deepcopy(snap)
    v2 = normalize({"title": "Новое", "blocks": [{"key": "A", "exercise_id": 1, "sets": 5, "reps": 2}]})
    build_prescription_snapshot(
        v2, workout_definition_id=1, workout_definition_version_id=2, version_no=2,
        exercises={1: ExerciseInfo(1, "Переименовано", 1, 10)}, resolved_at=NOW,
    )
    assert snap == frozen
    restored = snapshot_from_dict(snap)
    assert restored.title == "Старое"
    assert restored.blocks[0].exercise_display_name == "Подтягивания"
    assert describe(restored.blocks[0]) == "3 × 10"


# --- V1 → v2 ------------------------------------------------------------------------------


def _item(item_id, protocol, **kw) -> V1Item:
    return V1Item(item_id=item_id, exercise_id=kw.pop("exercise_id", 1), order_index=kw.pop("order", 0),
                  protocol=protocol, **kw)


def test_v1_reps_sets_maps_to_explicit_sets():
    content = content_from_v1("Объём ×5", [_item(4, {
        "type": "reps_sets", "prescription": {"source": "static", "sets": 5, "reps": 8}, "rest_seconds": 120,
    })])
    block = content.blocks[0]
    assert block.key == "i4e1"
    assert [s.target_reps for s in block.sets] == [8] * 5
    assert [s.rest_after_seconds for s in block.sets] == [120] * 4 + [None]
    assert describe(block) == "5 × 8"


def test_v1_max_effort_maps_to_max_sets_without_target():
    block = content_from_v1("Макс", [_item(1, {
        "type": "max_effort", "prescription": {"source": "static", "attempts": 4}, "rest_seconds": 120,
    })]).blocks[0]
    assert [s.kind for s in block.sets] == [SetKind.MAX_REPS] * 4
    assert all(s.target_reps is None for s in block.sets)
    assert [s.rest_after_seconds for s in block.sets] == [120, 120, 120, None]


def test_v1_max_effort_without_rest_defaults_to_zero_like_v1():
    block = content_from_v1("Макс", [_item(1, {
        "type": "max_effort", "prescription": {"source": "static", "attempts": 2},
    })]).blocks[0]
    assert [s.rest_after_seconds for s in block.sets] == [0, None]


def test_v1_time_sets_and_interval():
    content = content_from_v1("T", [
        _item(2, {"type": "time_sets", "prescription": {"source": "static", "sets": 2, "duration_seconds": 30},
                  "rest_seconds": 60}, order=1, exercise_id=3),
        _item(1, {"type": "interval", "total_duration_seconds": 180, "work_seconds": 10, "rest_seconds": 20,
                  "starts_with": "work"}, order=0),
    ])
    first, second = content.blocks
    assert first.key == "i1e1" and first.interval.rounds == 6 and first.interval.record_reps_per_round is False
    assert second.key == "i2e3" and describe(second) == "2 × 0:30"


def test_v1_interval_not_divisible_is_rejected_not_guessed():
    with pytest.raises(V1MappingError):
        content_from_v1("T", [_item(1, {"type": "interval", "total_duration_seconds": 100, "work_seconds": 10,
                                        "rest_seconds": 20, "starts_with": "work"})])


def test_v1_progression_maps_to_progression_block_with_role():
    content = content_from_v1("Курс", [_item(1, {
        "type": "reps_sets", "prescription": {"source": "progression"}, "rest_seconds": 180,
    }, progression_role="block_b")])
    block = content.blocks[0]
    assert block.source is BlockSource.PROGRESSION and block.progression_role == "block_b"
    with pytest.raises(V1MappingError):
        content_from_v1("Курс", [_item(1, {
            "type": "reps_sets", "prescription": {"source": "progression"}, "rest_seconds": 180,
        })])


def test_v1_legacy_columns_only_when_unambiguous():
    block = content_from_v1("L", [_item(1, None, sets=3, target_value=Decimal(12), target_unit="reps",
                                         rest_seconds=60)]).blocks[0]
    assert describe(block) == "3 × 12"
    for kwargs in (
        {"sets": 3, "target_value": None, "target_unit": "reps"},
        {"sets": 3, "target_value": Decimal("2.5"), "target_unit": "reps"},
        {"sets": 0, "target_value": Decimal(5), "target_unit": "reps"},
        {"sets": 3, "target_value": Decimal(5), "target_unit": "kg"},
    ):
        with pytest.raises(V1MappingError):
            content_from_v1("L", [_item(1, None, **kwargs)])


def test_v1_block_key_includes_exercise_so_it_never_names_two_exercises():
    protocol = {"type": "reps_sets", "prescription": {"source": "static", "sets": 1, "reps": 1}, "rest_seconds": 0}
    first = content_from_v1("K", [_item(7, protocol, exercise_id=1)]).blocks[0]
    second = content_from_v1("K", [_item(7, protocol, exercise_id=2)]).blocks[0]
    assert (first.key, second.key) == ("i7e1", "i7e2")
    edited = content_from_v1("K", [_item(7, {**protocol, "rest_seconds": 60}, exercise_id=1, order=3)]).blocks[0]
    assert edited.key == first.key  # обычная правка (отдых, порядок) ключ не меняет


def test_v1_protocol_that_is_not_an_object_is_flagged_not_crash():
    with pytest.raises(V1MappingError):
        content_from_v1("K", [_item(1, ["reps_sets"])])


def test_v1_empty_workout_rejected():
    with pytest.raises(V1MappingError):
        content_from_v1("Пусто", [])


def test_v1_conversion_is_deterministic_and_idempotent():
    items = [
        _item(9, {"type": "reps_sets", "prescription": {"source": "static", "sets": 3, "reps": 10},
                  "rest_seconds": 90}, order=1),
        _item(3, {"type": "max_effort", "prescription": {"source": "static", "attempts": 1},
                  "rest_seconds": 0}, order=0),
    ]
    first = content_from_v1("X", items)
    second = content_from_v1("X", list(reversed(items)))
    assert first == second
    assert content_hash(first) == content_hash(second)
    assert normalize(to_dict(first)) == first


# --- Exercise identity -----------------------------------------------------------------


def test_exercise_display_label_never_falls_back_to_slug():
    assert exercise_display_label("Подтягивания", "pull_ups") == "Подтягивания"
    assert exercise_display_label(None, "Отжимания") == "Отжимания"
    assert exercise_display_label(None, "block_a") == "Упражнение"
    assert exercise_display_label("user", None) == "Упражнение"


def test_slug_detection_and_analytics_identity():
    assert looks_like_slug("pull_ups") and looks_like_slug("block_a") and looks_like_slug("user")
    assert not looks_like_slug("Подтягивания")
    assert analytics_identity(7, 1) == 1
    assert analytics_identity(7, None) == 7


def test_legacy_category_mapping():
    assert category_slug_for_legacy("pull_ups") == "pull_ups"
    assert category_slug_for_legacy("Подтягивания") == "pull_ups"
    assert category_slug_for_legacy("user") == "my_exercises"
    assert category_slug_for_legacy("что-то новое") == "uncategorized"


# --- Снисходительное чтение истории (#303 review, §9.12) ---------------------------------------


def _stored(**block_overrides) -> dict:
    data = to_dict(normalize(_one_block(sets=3, reps=10, **block_overrides)))
    return copy.deepcopy(data)


def test_content_from_stored_verifies_hash_of_stored_json_not_renormalized():
    data = _stored()
    digest = content_hash(normalize(data))
    assert stored_content_hash(data) == digest
    assert content_from_stored(data, expected_hash=digest) == normalize(data)
    tampered = copy.deepcopy(data)
    tampered["blocks"][0]["sets"][0]["target_reps"] = 11
    with pytest.raises(WorkoutContentError) as exc:
        content_from_stored(tampered, expected_hash=digest)
    assert exc.value.code == "hash_mismatch"


def test_content_from_stored_accepts_rows_without_later_optional_fields_and_ignores_unknown():
    """Строка, записанная до появления необязательного поля, читается без него; поле,
    добавленное позже писателем, старому читателю не мешает; хеш — того, что хранится."""
    old_row = _stored()
    for block in old_row["blocks"]:
        del block["load"], block["progression_role"], block["source"]
        for set_ in block["sets"]:
            del set_["load"]
    newer_row = _stored()
    newer_row["blocks"][0]["notes"] = "добавлено будущей схемой"
    for row in (old_row, newer_row):
        content = content_from_stored(row, expected_hash=stored_content_hash(row))
        assert describe(content.blocks[0]) == "3 × 10"
        assert content.blocks[0].source is BlockSource.STATIC and content.blocks[0].load is None
    # Строгий normalize() такую историю отверг бы — для новых записей он и остаётся строгим.
    with pytest.raises(WorkoutContentError):
        normalize(newer_row)


def test_content_from_stored_does_not_rederive_defaults():
    row = _stored()
    row["blocks"][0]["prep_seconds"] = 0  # не умолчание сегодняшнего normalize() (5 у первого блока)
    content = content_from_stored(row, expected_hash=stored_content_hash(row))
    assert content.blocks[0].prep_seconds == 0


def test_snapshot_from_dict_is_lenient_for_later_optional_fields():
    snap = snapshot_to_dict(build_prescription_snapshot(
        normalize(_one_block(sets=3, reps=10)), workout_definition_id=1, workout_definition_version_id=1,
        version_no=1, exercises=EXERCISES, resolved_at=NOW,
    ))
    snap["blocks"][0]["future_field"] = {"x": 1}
    snap["blocks"][0]["sets"][0]["future_set_field"] = True
    snap["blocks"][0]["interval"] = None
    del snap["blocks"][0]["load"], snap["blocks"][0]["category_id"]
    for set_ in snap["blocks"][0]["sets"]:
        del set_["load"]
    restored = snapshot_from_dict(snap)
    assert describe(restored.blocks[0]) == "3 × 10"
    assert restored.blocks[0].category_id is None
