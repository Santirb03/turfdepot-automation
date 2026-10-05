import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from turfdepot.core.config import Settings
from turfdepot.main import create_app


def pytest_addoption(parser):
    parser.addoption("--pdf-test-fonts", choices=("calibri", "carlito"), default="calibri",
                     help="PDF test fonts only: Calibri locally, freely licensed Carlito in CI.")


def pytest_configure(config):
    if config.getoption("--pdf-test-fonts") == "carlito":
        # Register only inside pytest. Production always requires private Calibri.
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        font_dir = Path(__file__).parent / "assets" / "carlito"
        for name, filename in (("TurfCalibri", "Carlito-Regular.ttf"),
                               ("TurfCalibriBold", "Carlito-Bold.ttf")):
            pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))


@pytest.fixture(autouse=True)
def isolate_whatsapp_environment(monkeypatch):
    # Real Meta credentials must not enable outbound integrations in tests.
    for name in list(os.environ):
        if name.startswith("WHATSAPP_") or name == "INTERNAL_API_KEY":
            monkeypatch.delenv(name)


@pytest.fixture
def app():
    # Separate PostgreSQL schema per test; never drop or truncate application tables.
    settings = Settings(whatsapp_enabled=False)
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url:
        settings = Settings(database_url=database_url, whatsapp_enabled=False)
    url = settings.connection_url()
    schema = "test_" + uuid4().hex
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    settings = Settings(database_url=test_url.render_as_string(hide_password=False),
                        garden_prices={"jardin_plus": "300.00"}, whatsapp_enabled=False)
    # pydantic-settings merges dicts from env; isolate tests from the real catalog.
    settings.garden_prices = {"jardin_plus": Decimal("300.00")}
    application = create_app(settings)
    try:
        yield application
    finally:
        application.state.engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def payload():
    return {"customer_name": "Juan Perez", "customer_phone": "4421234567",
            "customer_location": "Juriquilla, Queretaro", "square_meters": 45,
            "garden_type": "jardin_plus", "extras": [{"name": "base", "price": 2500}]}
