from solution import TokenBucket


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_starts_full_and_drains():
    clock = Clock()
    b = TokenBucket(rate=1, capacity=3, clock=clock)
    assert [b.allow() for _ in range(4)] == [True, True, True, False]


def test_refills_over_time():
    clock = Clock()
    b = TokenBucket(rate=2, capacity=2, clock=clock)
    b.allow(2)
    clock.t = 0.5
    assert b.allow() and not b.allow()
