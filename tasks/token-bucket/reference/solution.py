"""Reference token bucket rate limiter."""

from __future__ import annotations

import time
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self, rate: float, capacity: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if rate <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self._rate = float(rate)
        self._capacity = float(capacity)
        self._clock = clock
        self._tokens = self._capacity
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)

    @property
    def tokens(self) -> float:
        self._refill()
        return self._tokens

    def allow(self, n: float = 1) -> bool:
        if n <= 0:
            raise ValueError("n must be positive")
        self._refill()
        if self._tokens + 1e-12 >= n:
            self._tokens = max(0.0, self._tokens - n)
            return True
        return False
