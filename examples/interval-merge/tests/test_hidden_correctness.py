import pytest

from solution import merge_intervals, parse_intervals


@pytest.mark.parametrize(
    "given, expected",
    [
        ([(5, 7), (1, 2), (2, 4)], [(1, 4), (5, 7)]),
        ([(1, 10), (2, 3), (4, 5)], [(1, 10)]),
        ([(0, 0), (0, 0)], [(0, 0)]),
        ([(-5, -1), (-3, 2)], [(-5, 2)]),
        ([(1, 2), (3, 4), (5, 6)], [(1, 2), (3, 4), (5, 6)]),
    ],
)
def test_merge_cases(given, expected):
    assert merge_intervals(given) == expected


def test_parse_whitespace():
    assert parse_intervals("  1-3 ,  5-8,10-10 ") == [(1, 3), (5, 8), (10, 10)]


def test_returns_tuples():
    out = merge_intervals([[1, 3], [2, 4]])
    assert out == [(1, 4)] and all(isinstance(x, tuple) for x in out)
