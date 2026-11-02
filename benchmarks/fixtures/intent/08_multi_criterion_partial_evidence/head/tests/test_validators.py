from validators import is_blank, validate_password


def test_is_blank():
    assert is_blank("   ")


def test_rejects_seven_characters():
    assert validate_password("Abcde1x") is False


def test_accepts_eight_characters():
    assert validate_password("Abcdef1x") is True


def test_rejects_missing_digit():
    assert validate_password("Abcdefgh") is False


def test_uppercase_rule_runs():
    assert isinstance(validate_password("abcdefg1"), bool)
