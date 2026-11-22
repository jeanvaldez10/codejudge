import pytest

from solution import LRUCache


@pytest.mark.parametrize("cap", [0, -1])
def test_invalid_capacity(cap):
    with pytest.raises(ValueError):
        LRUCache(cap)


def test_capacity_one():
    c = LRUCache(1)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") is None and c.get("b") == 2 and len(c) == 1


def test_contains_does_not_change_recency():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert "a" in c
    c.put("c", 3)
    assert "a" not in c and "b" in c


def test_stores_none_values():
    c = LRUCache(2)
    c.put("a", None)
    assert "a" in c and c.get("a", "default") is None


def test_falsy_keys():
    c = LRUCache(3)
    c.put(0, "zero")
    c.put("", "empty")
    assert c.get(0) == "zero" and c.get("") == "empty"
