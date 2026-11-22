import pytest

from solution import aggregate


def test_escaped_quotes_and_newlines_in_field():
    text = 'k,v\n"say ""hi""",1\n"multi\nline",2\n'
    assert aggregate(text, "k", "v") == {'say "hi"': 1.0, "multi\nline": 2.0}


def test_empty_input_and_header_only():
    assert aggregate("", "k", "v") == {}
    assert aggregate("k,v\n", "k", "v") == {}


def test_blank_lines_and_empty_values_skipped():
    text = "k,v\n\na,1\nb,\n\na, 2.5 \n"
    assert aggregate(text, "k", "v") == {"a": 3.5}


def test_missing_column():
    with pytest.raises(ValueError):
        aggregate("k,v\na,1\n", "k", "nope")


def test_short_row():
    with pytest.raises(ValueError):
        aggregate("k,v,w\na,1\n", "k", "v")


def test_non_numeric_value():
    with pytest.raises(ValueError):
        aggregate("k,v\na,abc\n", "k", "v")


def test_negative_and_scientific():
    assert aggregate("k,v\na,-1.5\na,2e1\n", "k", "v") == {"a": 18.5}
