from text_utils import slugify, title_case


def test_title_case():
    assert title_case("hello big world") == "Hello Big World"


def test_slugify_basic():
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_collapses_whitespace():
    assert slugify("  Multiple   spaces ") == "multiple-spaces"


def test_slugify_empty():
    assert slugify("") == ""


def test_slugify_treats_underscore_as_separator():
    assert slugify("Already-Slug_ified") == "already-slug-ified"
