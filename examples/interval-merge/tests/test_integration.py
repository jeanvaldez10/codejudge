from solution import merge_intervals, parse_intervals


def test_parse_then_merge_roundtrip():
    spec = "8-10, 1-3, 2-6, 15-18, 17-20"
    assert merge_intervals(parse_intervals(spec)) == [(1, 6), (8, 10), (15, 20)]


def test_large_input_stays_correct():
    data = [(i, i + 2) for i in range(0, 10_000, 2)]
    assert merge_intervals(data) == [(0, 10_000)]
