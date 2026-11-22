"""Reference deterministic topological sort (Kahn's algorithm + heap)."""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Mapping


class CycleError(ValueError):
    pass


def topological_sort(graph: Mapping[str, Iterable[str]]) -> list[str]:
    dependents: dict[str, set[str]] = {}
    indegree: dict[str, int] = {}
    for node, deps in graph.items():
        indegree.setdefault(node, 0)
        for dep in set(deps):
            indegree.setdefault(dep, 0)
            if node not in dependents.setdefault(dep, set()):
                dependents[dep].add(node)
                indegree[node] += 1
    ready = [n for n, d in indegree.items() if d == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for nxt in dependents.get(node, ()):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(ready, nxt)
    if len(order) != len(indegree):
        raise CycleError("graph contains a cycle")
    return order
