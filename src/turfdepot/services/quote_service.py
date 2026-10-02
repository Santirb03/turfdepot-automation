from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy.orm import Session

from turfdepot.db.models import Customer, Quote, QuoteExtra
from turfdepot.schemas.quote import QuoteCreate
from turfdepot.services.pricing import price_quote


def create_quote(session: Session, data: QuoteCreate, prices: Mapping[str, Decimal]) -> Quote:
    amounts = price_quote(data.square_meters, data.garden_type,
                          (extra.price for extra in data.extras), prices)
    # One transaction: a failed extra must not leave an orphan customer or quote.
    with session.begin():
        quote = Quote(
            customer=Customer(name=data.customer_name, phone=data.customer_phone,
                              location=data.customer_location),
            square_meters=data.square_meters, garden_type=data.garden_type,
            subtotal=amounts.subtotal, extras_total=amounts.extras_total, total=amounts.total,
            extras=[QuoteExtra(name=extra.name, price=extra.price) for extra in data.extras],
        )
        session.add(quote)
        session.flush()
        # Read PostgreSQL's normalized NUMERIC scales and server defaults.
        session.refresh(quote)
    return quote


def get_quote(session: Session, quote_id: int) -> Quote | None:
    return session.get(Quote, quote_id)
