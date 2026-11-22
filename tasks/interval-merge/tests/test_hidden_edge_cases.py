import pytest

from solution import merge_intervals, parse_intervals


def test_empty():
    assert merge_intervals([]) == []


def test_touching_merge():
    assert merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]


def test_single():
    assert merge_intervals([(4, 9)]) == [(4, 9)]


def test_does_not_mutate_input():
    data = [(3, 4), (1, 2)]
    merge_intervals(data)
    assert data == [(3, 4), (1, 2)]


def test_invalid_interval_raises():
    with pytest.raises(ValueError):
        merge_intervals([(5, 1)])


def test_parse_empty():
    assert parse_intervals("") == [] and parse_intervals("   ") == []


@pytest.mark.parametrize("bad", ["1-", "a-b", "1-2-3", "1-3,,4-5", "__import__('os')"])
def test_parse_malformed(bad):
    with pytest.raises(ValueError):
        parse_intervals(bad)


def test_negative_numbers_parse():
    assert parse_intervals("-5--1") == [(-5, -1)]
