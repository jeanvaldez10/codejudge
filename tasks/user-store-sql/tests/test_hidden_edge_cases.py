import sqlite3

import pytest

from solution import create_user, find_user, init_schema, search_users


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_schema(c)
    create_user(c, "admin", "admin@example.com")
    return c


def test_sql_injection_in_lookup(conn):
    assert find_user(conn, "x' OR '1'='1") is None
    assert find_user(conn, "admin' --") is None


def test_quotes_round_trip(conn):
    create_user(conn, "o'brien", "ob@example.com")
    assert find_user(conn, "o'brien")["email"] == "ob@example.com"


def test_like_wildcards_are_literal(conn):
    create_user(conn, "a_b", "x@example.com")
    create_user(conn, "axb", "y@example.com")
    create_user(conn, "100%", "z@example.com")
    assert [u["username"] for u in search_users(conn, "a_")] == ["a_b"]
    assert [u["username"] for u in search_users(conn, "%")] == []
    assert [u["username"] for u in search_users(conn, "100%")] == ["100%"]


def test_injection_in_search(conn):
    assert search_users(conn, "' OR 1=1 --") == []


def test_duplicate_username(conn):
    with pytest.raises(ValueError):
        create_user(conn, "admin", "other@example.com")


@pytest.mark.parametrize("email", ["", "no-at", "a@@b", "@b", "a@", "a@b@c"])
def test_invalid_email(conn, email):
    with pytest.raises(ValueError):
        create_user(conn, "someone", email)


def test_empty_username(conn):
    with pytest.raises(ValueError):
        create_user(conn, "", "e@example.com")
