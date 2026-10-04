from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from turfdepot.db.models import Customer, Quote, QuoteExtra


def test_create_get_and_persistence(client, app, payload):
    response = client.post("/quotes", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "quote_number", "customer_id", "square_meters", "garden_type", "subtotal",
                         "extras_total", "total", "status", "created_at"}
    assert body["subtotal"] == "13500.00"
    assert body["extras_total"] == "2500.00"
    assert body["total"] == "16000.00"
    assert body["status"] == "pending"
    assert datetime.fromisoformat(body["created_at"].replace("Z", "+00:00")).tzinfo is not None
    assert client.get(f'/quotes/{body["id"]}').json() == body
    # Independent session proves data was committed to PostgreSQL.
    with app.state.session_factory() as session:
        customer = session.get(Customer, body["customer_id"])
        assert (customer.name, customer.phone, customer.location) == (
            payload["customer_name"], payload["customer_phone"], payload["customer_location"])
        quote = session.get(Quote, body["id"])
        assert quote.square_meters == Decimal("45")
        assert quote.customer.id == customer.id
        assert len(quote.extras) == 1
        assert quote.extras[0].name == "base"
        assert quote.extras[0].price == Decimal("2500")


@pytest.mark.parametrize("changes", [
    {"square_meters": 0}, {"square_meters": -1}, {"square_meters": "NaN"},
    {"square_meters": "Infinity"}, {"square_meters": 1.001}, {"square_meters": 1000001},
    {"customer_name": " "}, {"customer_phone": "abcdefg"}, {"customer_phone": "-------"},
    {"customer_location": ""},
    {"garden_type": "unknown"}, {"extras": [{"name": "base", "price": -1}]},
    {"extras": [{"name": "base", "price": "0.001"}]}, {"unexpected": 1},
])
def test_invalid_requests_do_not_write(client, app, payload, changes):
    assert client.post("/quotes", json=payload | changes).status_code == 422
    with app.state.session_factory() as session:
        for model in (Customer, Quote, QuoteExtra):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_no_extras(client, payload):
    payload.pop("extras")
    response = client.post("/quotes", json=payload)
    assert response.status_code == 201
    assert response.json()["total"] == "13500.00"
    assert response.json()["extras_total"] == "0.00"


def test_fractional_amounts_and_price_snapshot(client, app, payload):
    app.state.settings.garden_prices = {"jardin_plus": Decimal("0.07")}
    payload.update(square_meters="1.5", extras=[{"name": "a", "price": "0.10"},
                                               {"name": "b", "price": "0.20"}])
    response = client.post("/quotes", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["subtotal"] == "0.11"
    assert body["extras_total"] == "0.30"
    assert body["total"] == "0.41"
    app.state.settings.garden_prices = {"jardin_plus": Decimal("999")}
    assert client.get(f'/quotes/{body["id"]}').json() == body


def test_not_found(client):
    assert client.get("/quotes/999").status_code == 404
    assert client.get("/quotes/0").status_code == 422
    assert client.get("/quotes/2147483648").status_code == 422


def test_missing_prices(client, app, payload):
    app.state.settings.garden_prices = {}
    assert client.post("/quotes", json=payload).status_code == 503
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 0


def test_transaction_rollback(client, app, payload):
    from sqlalchemy import event

    def fail_extra(mapper, connection, target):
        raise OperationalError("INSERT", {}, Exception("simulated failure"))

    event.listen(QuoteExtra, "before_insert", fail_extra)
    try:
        response = client.post("/quotes", json=payload)
        assert response.status_code == 503
        assert "INSERT" not in response.text
    finally:
        event.remove(QuoteExtra, "before_insert", fail_extra)
    with app.state.session_factory() as session:
        for model in (Customer, Quote, QuoteExtra):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_database_unavailable(client, app):
    with patch.object(app.state, "session_factory", side_effect=OperationalError("", {}, Exception())):
        assert client.get("/health").status_code == 503
