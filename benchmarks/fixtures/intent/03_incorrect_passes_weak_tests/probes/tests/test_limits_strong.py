from limits import clamp


def test_probe_clamp_above_returns_hi():
    assert clamp(50, 0, 10) == 10


def test_probe_clamp_below_returns_lo():
    assert clamp(-5, 0, 10) == 0


def test_probe_clamp_inside_unchanged():
    assert clamp(5, 0, 10) == 5
