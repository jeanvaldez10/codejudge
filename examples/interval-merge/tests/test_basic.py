from solution import merge_intervals, parse_intervals


def test_merges_overlapping():
    assert merge_intervals([(1, 3), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_disjoint_unchanged():
    assert merge_intervals([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]


def test_parse_simple():
    assert parse_intervals("1-3,5-8") == [(1, 3), (5, 8)]
