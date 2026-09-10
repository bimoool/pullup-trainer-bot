from app.domain.session import BlockLog


def test_block_log_volume_includes_max_set():
    log = BlockLog(working_reps=(15, 15, 13), max_reps=14)
    assert log.volume == 15 + 15 + 13 + 14


def test_block_log_volume_empty_working_reps():
    log = BlockLog(working_reps=(), max_reps=5)
    assert log.volume == 5


def test_block_log_best_set_picks_max_reps_when_it_is_highest():
    log = BlockLog(working_reps=(15, 15, 13), max_reps=17)
    assert log.best_set == 17


def test_block_log_best_set_picks_working_rep_when_it_beats_max_reps():
    # Редкий, но легальный случай: подход "на максимум" не обязан быть
    # лучшим фактическим результатом тренировки.
    log = BlockLog(working_reps=(15, 20, 13), max_reps=17)
    assert log.best_set == 20


def test_block_log_best_set_empty_working_reps():
    log = BlockLog(working_reps=(), max_reps=5)
    assert log.best_set == 5
