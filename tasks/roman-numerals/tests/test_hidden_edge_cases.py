import pytest

from solution import from_roman, to_roman


@pytest.mark.parametrize("n", [0, -1, 4000, 10**9])
def test_out_of_range(n):
    with pytest.raises(ValueError):
        to_roman(n)


@pytest.mark.parametrize("v", [True, 3.0, "4", None])
def test_wrong_type(v):
    with pytest.raises(TypeError):
        to_roman(v)


@pytest.mark.parametrize(
    "s", ["", "IIII", "VX", "IC", "MMMM", "iv", " IV", "IV ", "VV", "LL", "DD", "IL", "XM", "ABC", "IIX", "CMC"]
)
def test_rejects_non_canonical(s):
    with pytest.raises(ValueError):
        from_roman(s)
