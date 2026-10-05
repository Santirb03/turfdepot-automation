from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import func, select

from turfdepot.db.models import Conversation, Customer, Quote
from turfdepot.services.catalog import approved_prices
from turfdepot.services.conversation_service import parse_area


def send(client, message_id, text, phone="524421234567"):
    return client.post("/conversations/messages", json={
        "contact_phone": phone, "message_id": str(message_id), "text": text})


@pytest.mark.parametrize("value,area,confirm", [
    ("es de 30 x 22", "660", True), ("30 metros por 22 metros", "660", True),
    ("2,5 × 4", "10", True), ("40 m²", "40", False),
    ("40 metros cuadrados", "40", False), ("tiene 12.50", "12.50", False),
])
def test_area_parser(value, area, confirm):
    assert parse_area(value) == (Decimal(area), confirm)


@pytest.mark.parametrize("value", ["0", "-3", "nan", "infinity", "30 x", "40 pies", "1.001", "1000001", "1.11 x 1.11"])
def test_invalid_area(value):
    assert parse_area(value) is None


def test_santiago_flow_pdf_and_duplicate_completion(client, app):
    app.state.settings.garden_prices = approved_prices()
    assert send(client, 1, "hola").json()["state"] == "name"
    assert send(client, 2, "Santiago Rodriguez").json()["state"] == "area"
    area = send(client, 3, "es de 30 x 22").json()
    assert area["state"] == "confirm_area" and "660" in area["reply"]
    assert send(client, 4, "sí").json()["state"] == "location"
    result = send(client, 5, "Corregidora")
    assert result.status_code == 200
    body = result.json()
    assert body["state"] == "completed" and body["quote_number"] == 11001
    assert "teléfono" not in body["reply"]
    assert send(client, 5, "Corregidora").json() == body
    follow_up = send(client, 6, "gracias").json()
    assert follow_up["quote_id"] == body["quote_id"]
    assert follow_up["state"] == "completed" and follow_up["reply"] == ""
    pdf = client.get(body["pdf_url"])
    assert pdf.status_code == 200
    contents = "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    assert "Santiago Rodriguez" in contents and "Corregidora" in contents
    assert "229.680,00" in contents and "99.000,00" in contents
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Quote)) == 1
        assert session.scalar(select(func.count()).select_from(Customer)) == 1
        quote = session.get(Quote, body["quote_id"])
        assert quote.customer.phone == "524421234567"


def test_retry_invalid_correction_and_reopen_session(client, app):
    send(client, 1, "hola")
    assert send(client, 2, "123").json()["state"] == "name"
    send(client, 3, "Ana")
    assert send(client, 4, "no sé").json()["state"] == "area"
    send(client, 5, "30 x 22")
    assert send(client, 6, "tal vez").json()["state"] == "confirm_area"
    assert send(client, 7, "no").json()["state"] == "area"
    assert send(client, 8, "40").json()["state"] == "location"
    # Next request uses a new DB session; dispose the connection pool as well.
    app.state.engine.dispose()
    assert send(client, 9, "123").json()["state"] == "location"
    with app.state.session_factory() as session:
        conversation = session.get(Conversation, "524421234567")
        assert conversation.customer_name == "Ana"
        assert conversation.square_meters == Decimal("40")


def test_duplicate_concurrent_messages_and_contacts(client, app):
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: send(client, 1, "hola").json(), range(4)))
    assert all(response == responses[0] for response in responses)
    assert send(client, 1, "otro texto").status_code == 409
    assert send(client, 2, "Ana", phone="+524421234567").json()["state"] == "area"
    assert send(client, 1, "hola", phone="524421234568").json()["state"] == "name"


def test_failure_rolls_back_completion_and_can_retry(client, app, monkeypatch):
    from turfdepot.services import conversation_service
    from turfdepot.services.pdf_service import PdfUnavailable
    send(client, 1, "hola")
    send(client, 2, "Ana")
    send(client, 3, "40")
    assert send(client, 4, "Corregidora").status_code == 503
    app.state.settings.garden_prices = approved_prices()
    original = conversation_service.quote_pdf
    def fail(quote):
        raise PdfUnavailable("No se puede generar el PDF.")
    monkeypatch.setattr(conversation_service, "quote_pdf", fail)
    assert send(client, 4, "Corregidora").status_code == 409
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Quote)) == 0
        assert session.scalar(select(func.count()).select_from(Customer)) == 0
        assert session.get(Conversation, "524421234567").state == "location"
    monkeypatch.setattr(conversation_service, "quote_pdf", original)
    assert send(client, 4, "Corregidora").json()["state"] == "completed"


def test_concurrent_completion_only_creates_one_quote(client, app):
    app.state.settings.garden_prices = approved_prices()
    send(client, 1, "hola")
    send(client, 2, "Ana")
    send(client, 3, "40")
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: send(client, 4, "Corregidora").json(), range(4)))
    assert all(response == responses[0] for response in responses)
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Quote)) == 1


@pytest.mark.parametrize("field,value", [("contact_phone", "abc"), ("text", " "), ("message_id", "")])
def test_message_validation(client, field, value):
    payload = {"contact_phone": "524421234567", "message_id": "1", "text": "hola"}
    payload[field] = value
    assert client.post("/conversations/messages", json=payload).status_code == 422
