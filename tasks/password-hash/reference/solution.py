"""Reference password hashing with scrypt (stdlib only).

Format: ``scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>``
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
_DKLEN = 32
# Bounds for parameters read back from storage, so a tampered hash can't
# request an absurd amount of work.
_MAX_N, _MAX_R, _MAX_P = 2**20, 32, 16


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
        n_i, r_i, p_i = int(n), int(r), int(p)
        in_bounds = 1 < n_i <= _MAX_N and 0 < r_i <= _MAX_R and 0 < p_i <= _MAX_P
        if not in_bounds or not expected:
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=n_i, r=r_i, p=p_i, dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
