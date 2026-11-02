from report import summarize


def test_summarize_groups_and_sorts():
    rows = [("b", 2), ("a", 1), ("b", 3)]
    assert summarize(rows) == [("a", 1), ("b", 5)]
