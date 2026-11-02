from text_utils import title_case


def test_title_case():
    assert title_case("hello big world") == "Hello Big World"
