import pytest

from solution import safe_join


@pytest.mark.parametrize(
    "parts, expected",
    [
        (("a/./b/../c.txt",), "/srv/data/a/c.txt"),
        (("a", "b", "..", "c"), "/srv/data/a/c"),
        ((".",), "/srv/data"),
        (("a/..",), "/srv/data"),
        ((), "/srv/data"),
        (("a//b",), "/srv/data/a/b"),
        (("..data",), "/srv/data/..data"),
    ],
)
def test_normalizes(parts, expected):
    assert safe_join("/srv/data", *parts) == expected


def test_trailing_slash_on_base():
    assert safe_join("/srv/data/", "x") == "/srv/data/x"


def test_root_base():
    assert safe_join("/", "etc", "hosts") == "/etc/hosts"
