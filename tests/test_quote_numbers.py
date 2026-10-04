from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from turfdepot.db.schema import initialize_schema
from turfdepot.schemas.quote import QuoteCreate
from turfdepot.services.quote_service import create_quote


def test_number_starts_at_11001_and_survives_restart(client, app, payload):
    first = client.post("/quotes", json=payload).json()
    assert first["quote_number"] == 11001
    initialize_schema(app.state.engine)
    second = client.post("/quotes", json=payload).json()
    assert second["quote_number"] == 11002
    assert client.get(f'/quotes/{first["id"]}').json()["quote_number"] == 11001


def test_parallel_quotes_receive_unique_numbers(client, app, payload):
    def save_quote(index: int) -> int:
        data = QuoteCreate(**(payload | {"customer_name": f"Parallel {index}"}))
        with app.state.session_factory() as session:
            return create_quote(session, data, app.state.settings.garden_prices).quote_number

    with ThreadPoolExecutor(max_workers=4) as executor:
        numbers = list(executor.map(save_quote, range(8)))
    assert sorted(numbers) == list(range(11001, 11009))


def test_upgrade_existing_table_preserves_rows(app):
    engine = app.state.engine
    with engine.begin() as connection:
        connection.execute(text('''
            CREATE TABLE quotes (
                id SERIAL PRIMARY KEY, customer_id INTEGER, square_meters NUMERIC(10,2),
                garden_type VARCHAR(80), subtotal NUMERIC(18,2), extras_total NUMERIC(18,2),
                total NUMERIC(18,2), status VARCHAR(20), created_at TIMESTAMPTZ DEFAULT now()
            )
        '''))
        connection.execute(text("INSERT INTO quotes (garden_type, total) VALUES ('original', 100)"))
    initialize_schema(engine)
    initialize_schema(engine)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT garden_type, total, quote_number FROM quotes")).one()
        assert row.garden_type == "original"
        assert row.total == 100
        assert row.quote_number == 11001
