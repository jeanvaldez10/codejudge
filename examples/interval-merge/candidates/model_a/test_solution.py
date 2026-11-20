import pytest

from solution import merge_intervals, parse_intervals


def test_merge_overlapping_and_touching():
    assert merge_intervals([(1, 3), (3, 5), (7, 8)]) == [(1, 5), (7, 8)]


def test_merge_unsorted_and_empty():
    assert merge_intervals([(5, 6), (1, 2)]) == [(1, 2), (5, 6)]
    assert merge_intervals([]) == []


def test_merge_rejects_reversed():
    with pytest.raises(ValueError):
        merge_intervals([(3, 1)])


def test_parse():
    assert parse_intervals(" 1-3, 5-8 ") == [(1, 3), (5, 8)]
    assert parse_intervals("") == []


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_intervals("1-x")
