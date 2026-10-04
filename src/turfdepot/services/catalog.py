"""Tariffs approved from Cotizacion 10162 (MXN, 16% VAT already included)."""
from decimal import Decimal

MODELS = (
    ("san_mateo_20", "SAN MATEO 20", "348.00"),
    ("san_mateo_30", "SAN MATEO 30", "382.80"),
    ("santa_fe_20", "SANTA FE 20", "382.80"),
    ("v_lawn_27", "V LAWN 27", "429.20"),
    ("san_mateo_40", "SAN MATEO 40", "475.60"),
    ("santa_fe_30", "SANTA FE 30", "487.20"),
    ("v_lawn_30", "V LAWN 30", "475.60"),
    ("v_lawn_37", "V LAWN 37", "510.40"),
)


def approved_prices() -> dict[str, Decimal]:
    return {key: Decimal(price) for key, _, price in MODELS}
