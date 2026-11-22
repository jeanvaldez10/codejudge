import pytest

from solution import hash_password, verify_password


def test_empty_password_rejected():
    with pytest.raises(ValueError):
        hash_password("")


@pytest.mark.parametrize("stored", ["", "garbage", "$$$", "a" * 500, "scrypt$", "pbkdf2_sha256$x$y$z"])
def test_malformed_stored_returns_false(stored):
    assert verify_password("anything", stored) is False


def test_tampered_hash_returns_false():
    stored = hash_password("pw")
    flipped = stored[:-1] + ("A" if stored[-1] != "A" else "B")
    assert verify_password("pw", flipped) is False


def test_stored_is_str_and_reasonably_sized():
    stored = hash_password("pw")
    assert isinstance(stored, str) and 20 <= len(stored) <= 512
