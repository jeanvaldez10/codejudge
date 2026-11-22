"""Reference traversal-safe path join (lexical, POSIX)."""

from __future__ import annotations

import posixpath


def safe_join(base: str, *parts: str) -> str:
    if not posixpath.isabs(base):
        raise ValueError("base must be an absolute path")
    for part in parts:
        if "\x00" in part:
            raise ValueError("path contains a NUL byte")
        if posixpath.isabs(part):
            raise ValueError(f"absolute path not allowed: {part!r}")
    root = posixpath.normpath(base)
    target = posixpath.normpath(posixpath.join(root, *parts))
    if posixpath.commonpath([root, target]) != root:
        raise ValueError("path escapes the base directory")
    return target
