from solution import from_roman, to_roman


def test_roundtrip_full_range():
    for i in range(1, 4000):
        assert from_roman(to_roman(i)) == i


def test_all_outputs_unique():
    assert len({to_roman(i) for i in range(1, 4000)}) == 3999
