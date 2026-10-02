from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from turfdepot.pricing import decimal_subtotal


class PricingNotConfigured(ValueError):
    pass


class UnknownGardenType(ValueError):
    pass


@dataclass(frozen=True)
class PriceBreakdown:
    subtotal: Decimal
    extras_total: Decimal
    total: Decimal


def price_quote(square_meters: Decimal, garden_type: str,
                extra_prices: Iterable[Decimal], prices: Mapping[str, Decimal]) -> PriceBreakdown:
    if not prices:
        raise PricingNotConfigured("Configure GARDEN_PRICES antes de crear cotizaciones.")
    if garden_type not in prices:
        raise UnknownGardenType("El tipo de jardín no está configurado.")
    subtotal = decimal_subtotal(square_meters, prices[garden_type])
    extras = list(extra_prices)
    if any(not price.is_finite() or price < 0 or price != price.quantize(Decimal("0.01")) for price in extras):
        raise ValueError("Los extras deben ser importes no negativos con hasta dos decimales.")
    extras_total = sum(extras, Decimal("0.00"))
    return PriceBreakdown(subtotal, extras_total, subtotal + extras_total)
