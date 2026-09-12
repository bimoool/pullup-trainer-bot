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


# --- reported_volume (issue #88: итог за тренировку без раскладки по подходам) ---


def test_block_log_volume_uses_reported_volume_when_set():
    # Бэкдейт блока Б "только итог" без максимума: working_reps=(), max_reps=0,
    # но реальный итог за тренировку (60) не равен 0 — без reported_volume
    # volume ушёл бы в 0, что и было исходным багом issue #88.
    log = BlockLog(working_reps=(), max_reps=0, reported_volume=60)
    assert log.volume == 60


def test_block_log_volume_reported_volume_overrides_computed_sum():
    # reported_volume не СКЛАДЫВАЕТСЯ с working_reps/max_reps, а полностью
    # их заменяет — working_reps здесь всегда пуст на практике, но даже если
    # бы не был, приоритет должен быть за явно введённым итогом.
    log = BlockLog(working_reps=(10, 10), max_reps=5, reported_volume=60)
    assert log.volume == 60


def test_block_log_best_set_ignores_reported_volume():
    # best_set — метрика "лучший ОДИН подход", reported_volume (сумма за
    # тренировку) не должен в неё попадать — ровно тот баг, который чинит
    # issue #88 (итог, записанный как будто он и есть лучший подход).
    log = BlockLog(working_reps=(), max_reps=0, reported_volume=60)
    assert log.best_set == 0

    log_with_max = BlockLog(working_reps=(), max_reps=15, reported_volume=60)
    assert log_with_max.best_set == 15
