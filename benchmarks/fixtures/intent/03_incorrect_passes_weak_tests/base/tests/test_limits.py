from limits import is_between


def test_is_between_inclusive():
    assert is_between(10, 0, 10)
