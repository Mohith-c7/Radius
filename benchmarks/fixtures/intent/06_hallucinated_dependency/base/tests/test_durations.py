from durations import to_seconds


def test_to_seconds():
    assert to_seconds(1, 1, 1) == 3661
