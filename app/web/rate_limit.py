"""Небольшой in-process лимитер «token bucket» по ключу (id пользователя) с ограничением памяти.

Нужен точечно (Peer Insights, ревью #283): чтобы нельзя было сотнями запросов «развёртки»
собирать агрегаты разных когорт. Состояние — в памяти процесса: при нескольких воркерах лимит
действует на каждого отдельно (этого достаточно, чтобы остановить перебор); при перезапуске
сбрасывается. Ключи вытесняются по LRU (не больше `max_keys`), память не растёт."""

import time
from collections import OrderedDict
from collections.abc import Callable


class TokenBucketLimiter:
    def __init__(
        self, capacity: float, refill_per_second: float, max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1 or refill_per_second <= 0 or max_keys < 1:
            raise ValueError("capacity >= 1, refill_per_second > 0, max_keys >= 1")
        self._capacity = float(capacity)
        self._refill = float(refill_per_second)
        self._max_keys = max_keys
        self._clock = clock
        self._buckets: OrderedDict[object, tuple[float, float]] = OrderedDict()  # key -> (tokens, updated_at)

    def acquire(self, key: object) -> float:
        """0.0 — запрос разрешён (токен списан); иначе — через сколько секунд появится токен."""
        now = self._clock()
        tokens, updated = self._buckets.pop(key, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - updated) * self._refill)
        retry_after = 0.0
        if tokens >= 1:
            tokens -= 1
        else:
            retry_after = (1 - tokens) / self._refill
        self._buckets[key] = (tokens, now)  # вставка в конец = «недавно использован»
        while len(self._buckets) > self._max_keys:
            self._buckets.popitem(last=False)
        return retry_after

    def reset(self) -> None:
        self._buckets.clear()

    def __len__(self) -> int:
        return len(self._buckets)
