import pytest

from stock import OutOfStock, release, reserve, stock_value


def test_reserve_reduces_stock():
    assert reserve(10, 3) == 7


def test_reserve_exact_stock():
    assert reserve(5, 5) == 0


def test_reserve_more_than_stock_raises():
    with pytest.raises(OutOfStock):
        reserve(2, 3)


def test_reserve_rejects_non_positive():
    with pytest.raises(ValueError):
        reserve(10, 0)


def test_release_restores():
    assert release(7, 3) == 10


def test_stock_value():
    assert stock_value(3, 2.5) == 7.5
