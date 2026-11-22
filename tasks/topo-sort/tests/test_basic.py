import pytest

from solution import CycleError, topological_sort


def test_simple_order():
    assert topological_sort({"app": ["lib", "util"], "lib": ["util"]}) == ["util", "lib", "app"]


def test_cycle():
    with pytest.raises(CycleError):
        topological_sort({"a": ["b"], "b": ["a"]})
