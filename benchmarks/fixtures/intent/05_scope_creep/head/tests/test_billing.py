from billing import round_money


def test_round_money_two_places():
    assert round_money(1.234) == 1.23
