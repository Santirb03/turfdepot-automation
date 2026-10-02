from decimal import Decimal as D

import pytest

from turfdepot.services.pricing import PricingNotConfigured, UnknownGardenType, price_quote


def test_price_with_extras():
    result = price_quote(D("45"), "test", [D("2500"), D("0.25")], {"test": D("300")})
    assert result.subtotal == D("13500.00")
    assert result.extras_total == D("2500.25")
    assert result.total == D("16000.25")


def test_price_without_extras():
    assert price_quote(D("1.5"), "test", [], {"test": D("0.07")}).total == D("0.11")


def test_zero_price():
    assert price_quote(D("1"), "test", [], {"test": D("0")}).total == 0


@pytest.mark.parametrize("area", ["0", "-1", "NaN", "Infinity"])
def test_invalid_area(area):
    with pytest.raises(ValueError):
        price_quote(D(area), "test", [], {"test": D("1")})


@pytest.mark.parametrize("extra", ["-1", "NaN", "Infinity", "0.001"])
def test_invalid_extra(extra):
    with pytest.raises(ValueError):
        price_quote(D("1"), "test", [D(extra)], {"test": D("1")})


def test_missing_configuration():
    with pytest.raises(PricingNotConfigured):
        price_quote(D("1"), "test", [], {})
    with pytest.raises(UnknownGardenType):
        price_quote(D("1"), "unknown", [], {"test": D("1")})
