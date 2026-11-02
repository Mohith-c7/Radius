from report import summarize, top


def test_summarize_groups_and_sorts():
    rows = [("b", 2), ("a", 1), ("b", 3)]
    assert summarize(rows) == [("a", 1), ("b", 5)]


def test_top_is_bounded():
    rows = [("a", 1), ("b", 2), ("c", 3), ("d", 4)]
    assert len(top(rows)) <= 3
