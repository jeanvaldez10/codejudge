"""Reference SQLite user store (parameterised queries only)."""

from __future__ import annotations

import sqlite3
from typing import Any


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        " id INTEGER PRIMARY KEY,"
        " username TEXT UNIQUE NOT NULL,"
        " email TEXT NOT NULL)"
    )
    conn.commit()


def _valid_email(email: str) -> bool:
    local, sep, domain = email.partition("@")
    return bool(sep and local and domain and "@" not in domain)


def create_user(conn: sqlite3.Connection, username: str, email: str) -> int:
    if not username:
        raise ValueError("username must not be empty")
    if not _valid_email(email):
        raise ValueError(f"invalid email: {email!r}")
    try:
        cur = conn.execute(
            "INSERT INTO users (username, email) VALUES (?, ?)", (username, email)
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"username already exists: {username!r}") from None
    conn.commit()
    if cur.lastrowid is None:
        raise RuntimeError("insert did not return a row id")
    return cur.lastrowid


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {"id": row[0], "username": row[1], "email": row[2]}


def find_user(conn: sqlite3.Connection, username: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, username, email FROM users WHERE username = ?", (username,)
    ).fetchone()
    return _row(row) if row else None


def search_users(conn: sqlite3.Connection, prefix: str) -> list[dict[str, Any]]:
    # substr() comparison is case-sensitive and has no wildcard characters,
    # unlike LIKE (case-insensitive for ASCII) or GLOB.
    rows = conn.execute(
        "SELECT id, username, email FROM users"
        " WHERE substr(username, 1, ?) = ? ORDER BY username",
        (len(prefix), prefix),
    ).fetchall()
    return [_row(r) for r in rows]
