from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy.orm import Session

from turfdepot.db.models import Customer, Quote, QuoteExtra
from turfdepot.schemas.quote import QuoteCreate
from turfdepot.services.pricing import price_quote
from turfdepot.services.catalog import MODELS


def create_quote(session: Session, data: QuoteCreate, prices: Mapping[str, Decimal]) -> Quote:
    amounts = price_quote(data.square_meters, data.garden_type,
                          (extra.price for extra in data.extras), prices)
    with session.begin():
        quote = Quote(
            pdf_prices={key: str(prices[key]) for key, _, _ in MODELS if key in prices},
            base_price_per_m2=Decimal("150.00"),
            customer=Customer(name=data.customer_name, phone=data.customer_phone,
                              location=data.customer_location),
            square_meters=data.square_meters, garden_type=data.garden_type,
            subtotal=amounts.subtotal, extras_total=amounts.extras_total, total=amounts.total,
            extras=[QuoteExtra(name=extra.name, price=extra.price) for extra in data.extras],
        )
        session.add(quote)
        session.flush()
        session.refresh(quote)
    return quote


def get_quote(session: Session, quote_id: int) -> Quote | None:
    return session.get(Quote, quote_id)
