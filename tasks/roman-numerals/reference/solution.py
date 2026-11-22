"""Reference Roman numeral conversion."""

from __future__ import annotations

MAX_ROMAN = 3999
_TABLE = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)


def to_roman(n: int) -> str:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an int")
    if not 1 <= n <= MAX_ROMAN:
        raise ValueError("n must be in 1..3999")
    out = []
    for value, symbol in _TABLE:
        count, n = divmod(n, value)
        out.append(symbol * count)
    return "".join(out)


_CANONICAL: dict[str, int] = {to_roman(i): i for i in range(1, MAX_ROMAN + 1)}


def from_roman(s: str) -> int:
    try:
        return _CANONICAL[s]
    except (KeyError, TypeError):
        raise ValueError(f"not a canonical Roman numeral: {s!r}") from None
