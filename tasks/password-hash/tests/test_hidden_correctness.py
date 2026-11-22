from solution import hash_password, verify_password


def test_salted():
    assert hash_password("same") != hash_password("same")


def test_does_not_contain_password():
    stored = hash_password("hunter2-secret")
    assert "hunter2-secret" not in stored


def test_unicode_password():
    stored = hash_password("pässwörd🔑")
    assert verify_password("pässwörd🔑", stored)
    assert not verify_password("passwörd🔑", stored)


def test_similar_passwords_differ():
    stored = hash_password("abc123")
    assert not verify_password("abc124", stored)
    assert not verify_password("abc123 ", stored)
    assert not verify_password("ABC123", stored)
