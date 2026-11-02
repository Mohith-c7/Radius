from emails import domain_of


def test_domain_of():
    assert domain_of("ann@example.com") == "example.com"
