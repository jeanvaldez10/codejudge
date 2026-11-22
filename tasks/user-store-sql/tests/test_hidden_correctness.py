import sqlite3

import pytest

from solution import create_user, find_user, init_schema, search_users


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_schema(c)
    for name in ["alice", "alan", "bob", "Alfred"]:
        create_user(c, name, f"{name}@example.com")
    return c


def test_search_prefix_sorted(conn):
    assert [u["username"] for u in search_users(conn, "al")] == ["alan", "alice"]


def test_search_is_case_sensitive(conn):
    assert [u["username"] for u in search_users(conn, "Al")] == ["Alfred"]


def test_ids_are_distinct(conn):
    ids = {find_user(conn, n)["id"] for n in ["alice", "alan", "bob"]}
    assert len(ids) == 3


def test_init_schema_idempotent(conn):
    init_schema(conn)
    assert find_user(conn, "bob") is not None
