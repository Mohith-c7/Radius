from validators import validate_password


def test_probe_rejects_missing_uppercase():
    assert validate_password("abcdefg1") is False


def test_probe_rejects_common_password():
    assert validate_password("Password1") is False
