import pytest

from solution import safe_join


def test_joins_inside_base():
    assert safe_join("/srv/data", "reports", "q1.csv") == "/srv/data/reports/q1.csv"


def test_rejects_parent_escape():
    with pytest.raises(ValueError):
        safe_join("/srv/data", "../etc/passwd")
