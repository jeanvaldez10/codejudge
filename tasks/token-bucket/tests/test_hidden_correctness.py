import pytest

from solution import TokenBucket


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_never_exceeds_capacity():
    clock = Clock()
    b = TokenBucket(rate=10, capacity=5, clock=clock)
    clock.t += 1000
    assert b.tokens == pytest.approx(5)


def test_fractional_refill():
    # Binary-exact times and rates, so float rounding can't decide the outcome.
    clock = Clock()
    b = TokenBucket(rate=4, capacity=10, clock=clock)
    assert b.allow(10)
    clock.t += 0.375
    assert b.tokens == pytest.approx(1.5)
    assert b.allow(1.5)
    assert b.tokens == pytest.approx(0, abs=1e-9)


def test_failed_allow_consumes_nothing():
    clock = Clock()
    b = TokenBucket(rate=1, capacity=3, clock=clock)
    assert not b.allow(4)
    assert b.tokens == pytest.approx(3)


def test_sustained_rate():
    clock = Clock()
    b = TokenBucket(rate=8, capacity=1, clock=clock)
    allowed = 0
    for _ in range(1000):
        clock.t += 0.125
        allowed += b.allow()
    assert allowed == 1000
