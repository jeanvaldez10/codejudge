import pytest

from solution import CycleError, topological_sort


def test_empty():
    assert topological_sort({}) == []


def test_self_loop():
    with pytest.raises(CycleError):
        topological_sort({"a": ["a"]})


def test_cycle_error_is_value_error():
    with pytest.raises(ValueError):
        topological_sort({"a": ["b"], "b": ["c"], "c": ["a"], "d": []})


def test_duplicate_dependencies():
    assert topological_sort({"b": ["a", "a", "a"]}) == ["a", "b"]


def test_does_not_mutate_input():
    graph = {"b": ["a"], "c": ["b"]}
    topological_sort(graph)
    assert graph == {"b": ["a"], "c": ["b"]}


def test_deep_chain_no_recursion_error():
    n = 20_000
    graph = {f"{i:05d}": [f"{i - 1:05d}"] for i in range(1, n)}
    assert topological_sort(graph)[:3] == ["00000", "00001", "00002"]
