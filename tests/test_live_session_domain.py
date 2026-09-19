"""app.domain.live_session — чистая машина фаз живой сессии, без БД (тот же
принцип, что tests/test_progression_strategy.py: domain-тесты живут прямо в
tests/, не в подпапке). Проходит EXACT последовательность фаз для
конкретных конфигураций блоков — доказательство "не падает" здесь
недостаточно (см. "Стиль тестирования", docs/testing.md), каждый шаг
сверяется с точным ожидаемым (phase_name, block_index, set_number)."""

from app.domain.live_session import (
    DEFAULT_REST_SECONDS,
    GET_READY_SECONDS,
    BlockPlan,
    PhaseState,
    SessionPhaseName,
    initial_phase,
    next_phase,
)


def test_initial_phase_is_get_ready_of_first_block_first_set():
    state = initial_phase([BlockPlan(sets_count=2)])

    assert state == PhaseState(
        phase_name=SessionPhaseName.GET_READY, block_index=0, set_number=1,
        ends_at_offset_seconds=GET_READY_SECONDS,
    )


def test_initial_phase_with_no_blocks_is_done_defensively():
    state = initial_phase([])

    assert state == PhaseState(
        phase_name=SessionPhaseName.DONE, block_index=0, set_number=1, ends_at_offset_seconds=None,
    )


def test_single_block_two_sets_full_sequence():
    """blocks=[BlockPlan(2)]: get_ready -> go -> rest -> get_ready -> go ->
    done — ровно 2 подхода одного блока, второй подход завершает сессию
    сразу после go (нет rest после последнего подхода)."""
    blocks = [BlockPlan(sets_count=2)]
    state = initial_phase(blocks)
    assert state == PhaseState(SessionPhaseName.GET_READY, 0, 1, GET_READY_SECONDS)

    state = next_phase(state, blocks)
    assert state == PhaseState(SessionPhaseName.GO, 0, 1, None)

    state = next_phase(state, blocks)
    assert state == PhaseState(SessionPhaseName.REST, 0, 1, DEFAULT_REST_SECONDS)

    state = next_phase(state, blocks)
    assert state == PhaseState(SessionPhaseName.GET_READY, 0, 2, GET_READY_SECONDS)

    state = next_phase(state, blocks)
    assert state == PhaseState(SessionPhaseName.GO, 0, 2, None)

    state = next_phase(state, blocks)
    assert state == PhaseState(SessionPhaseName.DONE, 0, 2, None)

    # done идемпотентно — повторный next_phase не падает и не меняет состояние.
    state = next_phase(state, blocks)
    assert state == PhaseState(SessionPhaseName.DONE, 0, 2, None)


def test_two_blocks_transition_skips_rest_between_blocks():
    """blocks=[BlockPlan(2), BlockPlan(1)]: последний подход НЕпоследнего
    блока идёт сразу в get_ready следующего блока, БЕЗ фазы rest — rest
    существует только МЕЖДУ подходами одного блока."""
    blocks = [BlockPlan(sets_count=2), BlockPlan(sets_count=1)]
    state = initial_phase(blocks)
    assert state == PhaseState(SessionPhaseName.GET_READY, 0, 1, GET_READY_SECONDS)

    state = next_phase(state, blocks)  # go, block 0 set 1
    assert state == PhaseState(SessionPhaseName.GO, 0, 1, None)

    state = next_phase(state, blocks)  # rest, block 0 set 1 (не последний подход блока)
    assert state == PhaseState(SessionPhaseName.REST, 0, 1, DEFAULT_REST_SECONDS)

    state = next_phase(state, blocks)  # get_ready, block 0 set 2
    assert state == PhaseState(SessionPhaseName.GET_READY, 0, 2, GET_READY_SECONDS)

    state = next_phase(state, blocks)  # go, block 0 set 2 (последний подход блока 0)
    assert state == PhaseState(SessionPhaseName.GO, 0, 2, None)

    state = next_phase(state, blocks)  # get_ready блока 1, БЕЗ rest
    assert state == PhaseState(SessionPhaseName.GET_READY, 1, 1, GET_READY_SECONDS)

    state = next_phase(state, blocks)  # go, block 1 set 1
    assert state == PhaseState(SessionPhaseName.GO, 1, 1, None)

    state = next_phase(state, blocks)  # последний подход последнего блока -> done
    assert state == PhaseState(SessionPhaseName.DONE, 1, 1, None)


def test_next_phase_uses_custom_rest_seconds():
    blocks = [BlockPlan(sets_count=2)]
    state = PhaseState(SessionPhaseName.GO, 0, 1, None)

    state = next_phase(state, blocks, rest_seconds=45)

    assert state == PhaseState(SessionPhaseName.REST, 0, 1, 45)
