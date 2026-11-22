import pytest

from solution import safe_join

ATTACKS = [
    ("..",),
    ("../data2/secret",),  # sibling directory sharing the base's prefix
    ("a/../../etc",),
    ("a", "..", "..", "x"),
    ("/etc/passwd",),
    ("a", "/etc/passwd"),
    ("file\x00.txt",),
    ("a/b/../../../srv/data/x/../../../etc",),
]


@pytest.mark.parametrize("parts", ATTACKS)
def test_rejects(parts):
    with pytest.raises(ValueError):
        safe_join("/srv/data", *parts)


def test_relative_base_rejected():
    with pytest.raises(ValueError):
        safe_join("srv/data", "x")


def test_reentering_base_is_allowed():
    assert safe_join("/srv/data", "../data/x") == "/srv/data/x"
