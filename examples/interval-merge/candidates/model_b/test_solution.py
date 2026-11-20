from solution import merge_intervals, parse_intervals


def test_merge():
    assert merge_intervals([(1, 3), (2, 4)]) == [(1, 4)]


def test_parse():
    assert parse_intervals("1-2") == [(1, 2)]
