from validators import is_blank


def test_is_blank():
    assert is_blank("   ")
