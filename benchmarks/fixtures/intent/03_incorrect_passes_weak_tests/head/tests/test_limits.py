from limits import clamp, is_between


def test_is_between_inclusive():
    assert is_between(10, 0, 10)


def test_clamp_above_is_bounded():
    assert clamp(50, 0, 10) <= 10


def test_clamp_returns_an_int():
    assert isinstance(clamp(-5, 0, 10), int)


def test_clamp_inside_stays_in_range():
    assert clamp(5, 0, 10) in range(0, 11)
