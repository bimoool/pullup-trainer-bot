"""TokenBucketLimiter (app/web/rate_limit.py): ёмкость, пополнение со временем, изоляция ключей,
LRU-вытеснение."""

import pytest

from app.web.rate_limit import TokenBucketLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_burst_up_to_capacity_then_blocked_with_retry_after():
    clock = Clock()
    limiter = TokenBucketLimiter(capacity=3, refill_per_second=0.5, clock=clock)
    assert [limiter.acquire("u") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limiter.acquire("u") == pytest.approx(2.0)  # токен через 1 / 0.5 с


def test_tokens_refill_over_time_but_never_above_capacity():
    clock = Clock()
    limiter = TokenBucketLimiter(capacity=2, refill_per_second=1.0, clock=clock)
    limiter.acquire("u")
    limiter.acquire("u")
    assert limiter.acquire("u") > 0
    clock.now += 1.0
    assert limiter.acquire("u") == 0.0
    clock.now += 3600
    assert [limiter.acquire("u") for _ in range(2)] == [0.0, 0.0]
    assert limiter.acquire("u") > 0  # накопилось не больше capacity


def test_keys_are_independent():
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=0.1, clock=Clock())
    assert limiter.acquire("a") == 0.0 and limiter.acquire("a") > 0
    assert limiter.acquire("b") == 0.0


def test_lru_eviction_bounds_memory():
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=0.1, max_keys=3, clock=Clock())
    for key in ("a", "b", "c", "d"):
        limiter.acquire(key)
    assert len(limiter) == 3
    assert limiter.acquire("a") == 0.0  # «a» вытеснен — снова полный бакет
    assert limiter.acquire("d") > 0  # недавний ключ помнится


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        TokenBucketLimiter(capacity=0, refill_per_second=1)
