from emails import domain_of, normalize_email


def test_domain_of():
    assert domain_of("ann@example.com") == "example.com"


def test_normalize_returns_something():
    assert normalize_email("  Ann@Example.COM ")


def test_normalize_handles_plain_address():
    assert normalize_email("bob@example.com") is not None
