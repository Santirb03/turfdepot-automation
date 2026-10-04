from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from turfdepot.services.catalog import MODELS, approved_prices
from turfdepot.services.pdf_service import PdfQuote, PdfUnavailable, render_pdf


def test_pdf_all_models_and_base_without_separate_vat():
    data = PdfQuote(11001, "Juan Pérez", "Juriquilla, Querétaro", Decimal("40"), date(2026, 10, 2),
                    {key: str(price) for key, price in approved_prices().items()}, Decimal("150"))
    reader = PdfReader(BytesIO(render_pdf(data)))
    assert len(reader.pages) == 3
    text = "\n".join(page.extract_text() for page in reader.pages)
    for _, name, _ in MODELS:
        assert name in text
    for total in ("13.920,00", "15.312,00", "17.168,00", "19.024,00", "19.488,00", "20.416,00", "6.000,00"):
        assert total in text
    assert "Juan Pérez" in text and "Juriquilla, Querétaro" in text
    assert "11001" in text and "viernes 2 de octubre de 2026" in text
    assert "PREPARACIÓN DE BASE" in text
    assert "IVA" not in text
    assert "Carlos" not in text and "Marulanda" not in text and "10162" not in text
    assert "150,00" in text
    template = PdfReader(Path(__file__).resolve().parents[1] / "src/turfdepot/assets/quote-template.pdf")
    for actual, original in zip(reader.pages, template.pages):
        assert [image.data for image in actual.images] == [image.data for image in original.images]


def test_pdf_download_and_saved_price_snapshot(client, app, payload):
    app.state.settings.garden_prices = approved_prices()
    payload.update(garden_type="san_mateo_20", square_meters=14, extras=[])
    created = client.post("/quotes", json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["quote_number"] == 11001
    assert body["total"] == "4872.00"
    app.state.settings.garden_prices = {key: Decimal("1") for key, _, _ in MODELS}
    response = client.get(f'/quotes/{body["id"]}/pdf')
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'Cotizacion-11001.pdf' in response.headers["content-disposition"]
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "4.872,00" in text and "7.145,60" in text and "2.100,00" in text
    assert "11001" in text


def test_pdf_missing_and_incomplete_catalog(client, payload):
    assert client.get("/quotes/999/pdf").status_code == 404
    payload["extras"] = []
    body = client.post("/quotes", json=payload).json()
    response = client.get(f'/quotes/{body["id"]}/pdf')
    assert response.status_code == 409


def test_pdf_rejects_extra_charges(client, app, payload):
    app.state.settings.garden_prices = approved_prices()
    payload["garden_type"] = "san_mateo_20"
    body = client.post("/quotes", json=payload).json()
    assert client.get(f'/quotes/{body["id"]}/pdf').status_code == 409


def test_template_contains_no_previous_customer():
    template = Path(__file__).resolve().parents[1] / "src/turfdepot/assets/quote-template.pdf"
    text = "\n".join(page.extract_text() for page in PdfReader(template).pages)
    assert "Carlos" not in text and "Marulanda" not in text and "10162" not in text
    assert "viernes 28 de noviembre de 2025" not in text


def test_pdf_does_not_truncate_overlong_customer_name():
    data = PdfQuote(11001, "W"*150, "Querétaro", Decimal("14"), date(2026, 10, 2),
                    {key: str(price) for key, price in approved_prices().items()}, Decimal("150"))
    with pytest.raises(PdfUnavailable, match="demasiado largo"):
        render_pdf(data)
