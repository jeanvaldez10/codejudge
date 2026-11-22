import sqlite3

from solution import create_user, find_user, init_schema


def test_create_and_find():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    uid = create_user(conn, "ada", "ada@example.com")
    assert find_user(conn, "ada") == {"id": uid, "username": "ada", "email": "ada@example.com"}
    assert find_user(conn, "bob") is None
