import pytest

from turfdepot.models import GrassProduct
from turfdepot.pricing import (
    calculate_subtotal,
    calculate_vat,
    calculate_total,
    create_quote_item,
)


def test_calculate_subtotal():
    assert calculate_subtotal(14, 300) == 4200


def test_calculate_vat():
    assert calculate_vat(4200) == 672


def test_calculate_total():
    assert calculate_total(4200, 672) == 4872


def test_create_quote_item():
    product = GrassProduct(
        name="San Mateo 20",
        price_per_m2=300,
    )

    quote_item = create_quote_item(
        product=product,
        square_meters=14,
    )

    assert quote_item.product.name == "San Mateo 20"
    assert quote_item.product.price_per_m2 == 300
    assert quote_item.square_meters == 14
    assert quote_item.subtotal == 4200
    assert quote_item.vat == 672
    assert quote_item.total == 4872


def test_rejects_zero_square_meters():
    with pytest.raises(
        ValueError,
        match="Los metros cuadrados deben ser mayores que cero.",
    ):
        calculate_subtotal(0, 300)


def test_rejects_negative_square_meters():
    with pytest.raises(
        ValueError,
        match="Los metros cuadrados deben ser mayores que cero.",
    ):
        calculate_subtotal(-5, 300)


def test_rejects_negative_price():
    with pytest.raises(
        ValueError,
        match="El precio por metro cuadrado no puede ser negativo.",
    ):
        calculate_subtotal(14, -300)


def test_rejects_negative_subtotal_for_vat():
    with pytest.raises(
        ValueError,
        match="El subtotal no puede ser negativo.",
    ):
        calculate_vat(-100)


def test_rejects_invalid_vat_rate():
    with pytest.raises(
        ValueError,
        match="La tasa de IVA debe estar entre 0 y 1.",
    ):
        calculate_vat(4200, 1.5)


def test_rejects_negative_vat():
    with pytest.raises(
        ValueError,
        match="El IVA no puede ser negativo.",
    ):
        calculate_total(4200, -100)