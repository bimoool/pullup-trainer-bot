"""План Live Engine v2 из синтезированного снимка (issue #306 решение владельца п. 5 × #305 V5.6): явный отдых
из снимка (рецепт курса: 240/30 → 900 → 180) важнее умолчаний движка; без него — прежние умолчания."""

from app.domain.live_engine_plan import (
    DEFAULT_BLOCK_REST_SECONDS,
    SYSTEM_DEFAULT_REST_SECONDS,
    FallbackTarget,
    fallback_block,
    finalize_plan,
)

REPS = [FallbackTarget("reps", 7), FallbackTarget("reps", 7), FallbackTarget("reps", 7), FallbackTarget("reps", 0, True)]


def test_explicit_set_and_block_rest_override_the_fallbacks():
    block = fallback_block(
        REPS, rest_seconds=None, interval=None, is_first_block=True, set_rests=[240, 240, 240, None],
        block_rest_seconds=900,
    )
    assert [s["rest_after_seconds"] for s in block["sets"]] == [240, 240, 240, None]
    assert block["rest_after_block_seconds"] == 900


def test_explicit_rest_beats_the_v1_protocol_rest_too():
    block = fallback_block(REPS, rest_seconds=60, interval=None, is_first_block=False, set_rests=[30, 30, 30, None])
    assert [s["rest_after_seconds"] for s in block["sets"]] == [30, 30, 30, None]


def test_without_explicit_values_the_fallbacks_are_unchanged():
    block = fallback_block(REPS, rest_seconds=None, interval=None, is_first_block=True)
    assert [s["rest_after_seconds"] for s in block["sets"]] == [SYSTEM_DEFAULT_REST_SECONDS] * 3 + [None]
    assert block["rest_after_block_seconds"] == DEFAULT_BLOCK_REST_SECONDS
    protocol_rest = fallback_block(REPS, rest_seconds=45, interval=None, is_first_block=True, set_rests=[None] * 4)
    assert [s["rest_after_seconds"] for s in protocol_rest["sets"]] == [45, 45, 45, None]


def test_mismatched_or_invalid_explicit_values_are_ignored():
    wrong_length = fallback_block(REPS, rest_seconds=None, interval=None, is_first_block=True, set_rests=[240])
    assert [s["rest_after_seconds"] for s in wrong_length["sets"]] == [SYSTEM_DEFAULT_REST_SECONDS] * 3 + [None]
    invalid = fallback_block(
        REPS, rest_seconds=None, interval=None, is_first_block=True, set_rests=[-1, True, "240", None],
        block_rest_seconds="900",
    )
    assert [s["rest_after_seconds"] for s in invalid["sets"]] == [SYSTEM_DEFAULT_REST_SECONDS] * 3 + [None]
    assert invalid["rest_after_block_seconds"] == DEFAULT_BLOCK_REST_SECONDS
    empty = fallback_block([], rest_seconds=None, interval=None, is_first_block=True, set_rests=[])
    assert len(empty["sets"]) == 1


def test_last_block_still_has_no_rest_after_it():
    blocks = [
        fallback_block(REPS, rest_seconds=None, interval=None, is_first_block=True, block_rest_seconds=900),
        fallback_block(REPS, rest_seconds=None, interval=None, is_first_block=False, block_rest_seconds=900),
    ]
    plan = finalize_plan(blocks)
    assert [b["rest_after_block_seconds"] for b in plan["blocks"]] == [900, None]
