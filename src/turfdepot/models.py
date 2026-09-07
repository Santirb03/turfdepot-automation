from dataclasses import dataclass


@dataclass
class GrassProduct:
    name: str
    price_per_m2: float


@dataclass
class QuoteItem:
    product: GrassProduct
    square_meters: float
    subtotal: float
    vat: float
    total: float