"""Interval utilities."""

from __future__ import annotations

import re
from collections.abc import Iterable

Interval = tuple[int, int]

_ITEM = re.compile(r"^\s*(-?\d+)\s*-\s*(-?\d+)\s*$")


def merge_intervals(intervals: Iterable[Iterable[int]]) -> list[Interval]:
    """Merge overlapping or touching closed intervals, sorted by start.

    Runs in O(n log n) time and does not mutate its input.
    """
    normalized: list[Interval] = []
    for item in intervals:
        start, end = item
        if start > end:
            raise ValueError(f"invalid interval ({start}, {end}): start > end")
        normalized.append((start, end))
    normalized.sort()

    merged: list[Interval] = []
    for start, end in normalized:
        if merged and start <= merged[-1][1]:
            last_start, last_end = merged[-1]
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def parse_intervals(spec: str) -> list[Interval]:
    """Parse ``"1-3, 5-8"`` into ``[(1, 3), (5, 8)]``."""
    if not spec.strip():
        return []
    result: list[Interval] = []
    for raw in spec.split(","):
        match = _ITEM.match(raw)
        if match is None:
            raise ValueError(f"malformed interval: {raw.strip()!r}")
        result.append((int(match.group(1)), int(match.group(2))))
    return result
