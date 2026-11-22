import pytest

from solution import TokenBucket


class Clock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


@pytest.mark.parametrize("rate, cap", [(0, 1), (-1, 1), (1, 0), (1, -5)])
def test_invalid_construction(rate, cap):
    with pytest.raises(ValueError):
        TokenBucket(rate, cap, clock=Clock())


@pytest.mark.parametrize("n", [0, -1])
def test_invalid_n(n):
    with pytest.raises(ValueError):
        TokenBucket(1, 1, clock=Clock()).allow(n)


def test_clock_going_backwards():
    clock = Clock()
    b = TokenBucket(rate=1, capacity=2, clock=clock)
    b.allow(2)
    clock.t -= 10
    assert b.tokens == pytest.approx(0, abs=1e-9)
    assert not b.allow()
    clock.t += 1000
    assert b.tokens == pytest.approx(2)


def test_tokens_is_read_only():
    b = TokenBucket(1, 1, clock=Clock())
    with pytest.raises(AttributeError):
        b.tokens = 100


def test_uses_monotonic_by_default():
    assert TokenBucket(1, 1).allow()
