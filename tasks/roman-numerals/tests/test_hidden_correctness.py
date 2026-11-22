import pytest

from solution import from_roman, to_roman

CASES = [(1, "I"), (3, "III"), (9, "IX"), (14, "XIV"), (40, "XL"), (90, "XC"),
         (400, "CD"), (900, "CM"), (2024, "MMXXIV"), (3999, "MMMCMXCIX"), (444, "CDXLIV")]


@pytest.mark.parametrize("n, s", CASES)
def test_to_roman(n, s):
    assert to_roman(n) == s


@pytest.mark.parametrize("n, s", CASES)
def test_from_roman(n, s):
    assert from_roman(s) == n
