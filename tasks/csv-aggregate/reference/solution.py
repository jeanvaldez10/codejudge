"""Reference CSV group-by aggregation."""

from __future__ import annotations

import csv
import io


def aggregate(csv_text: str, key: str, value: str) -> dict[str, float]:
    rows = csv.reader(io.StringIO(csv_text, newline=""))
    header = next(rows, None)
    if header is None:
        return {}
    try:
        k_idx, v_idx = header.index(key), header.index(value)
    except ValueError:
        raise ValueError(f"unknown column: {key!r} or {value!r}") from None
    totals: dict[str, float] = {}
    for row in rows:
        if not row:
            continue
        if len(row) < len(header):
            raise ValueError(
                f"row {rows.line_num} has {len(row)} cells, expected {len(header)}"
            )
        raw = row[v_idx].strip()
        if not raw:
            continue
        try:
            amount = float(raw)
        except ValueError:
            raise ValueError(f"row {rows.line_num}: {raw!r} is not a number") from None
        totals[row[k_idx]] = totals.get(row[k_idx], 0.0) + amount
    return totals
