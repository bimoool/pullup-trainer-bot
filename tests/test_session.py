from app.domain.session import BlockLog


def test_block_log_volume_includes_max_set():
    log = BlockLog(working_reps=(15, 15, 13), max_reps=14)
    assert log.volume == 15 + 15 + 13 + 14


def test_block_log_volume_empty_working_reps():
    log = BlockLog(working_reps=(), max_reps=5)
    assert log.volume == 5
