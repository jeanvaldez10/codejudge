from typing import List, Tuple


def merge_intervals(intervals: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    # Repeatedly merge any pair that overlaps until nothing changes.
    intervals.sort()
    changed = True
    while changed:
        changed = False
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                a, b = intervals[i], intervals[j]
                if a[1] > b[0] and b[1] > a[0]:
                    intervals[i] = (min(a[0], b[0]), max(a[1], b[1]))
                    del intervals[j]
                    changed = True
                    break
            if changed:
                break
    return intervals


def parse_intervals(spec: str) -> List[Tuple[int, int]]:
    out = []
    for item in spec.replace(" ", "").split(","):
        if item == "":
            continue
        lo, hi = item.split("-")
        out.append((int(lo), int(hi)))
    return out
