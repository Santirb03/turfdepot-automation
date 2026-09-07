from dataclasses import dataclass


@dataclass(frozen=True)
class GrassProduct:
    name: str
    price_per_m2: float


@dataclass(frozen=True)
class QuoteItem:
    product: GrassProduct
    square_meters: float
    subtotal: float
    vat: float
    total: float