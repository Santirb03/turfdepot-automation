"""Small, additive schema upgrade for the first PDF milestone. Never drops data."""
from sqlalchemy import Engine, inspect, text

from turfdepot.db.models import Base, quote_number_sequence


def initialize_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        # Serialize concurrent app startups, scoped to the current test/app schema.
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(current_schema() || '_turfdepot_schema'))"))
        sequence_existed = inspect(connection).has_sequence("quote_number_seq")
        quote_number_sequence.create(connection, checkfirst=True)
        Base.metadata.create_all(connection)
        connection.execute(text("ALTER TABLE quotes ADD COLUMN IF NOT EXISTS quote_number INTEGER"))
        connection.execute(text("ALTER TABLE quotes ADD COLUMN IF NOT EXISTS pdf_prices JSON"))
        connection.execute(text("ALTER TABLE quotes ADD COLUMN IF NOT EXISTS base_price_per_m2 NUMERIC(10,2)"))
        # Initialize a newly created sequence only. Never reset it on app restart:
        # another worker may be issuing a quote at the same time.
        if not sequence_existed:
            connection.execute(text("""
                SELECT setval('quote_number_seq', GREATEST(
                    COALESCE((SELECT MAX(quote_number) FROM quotes), 11000), 11000
                ), true)
            """))
        connection.execute(text("""
            UPDATE quotes SET quote_number = nextval('quote_number_seq')
            WHERE quote_number IS NULL
        """))
        connection.execute(text("ALTER TABLE quotes ALTER COLUMN quote_number SET DEFAULT nextval('quote_number_seq')"))
        connection.execute(text("ALTER TABLE quotes ALTER COLUMN quote_number SET NOT NULL"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS quotes_quote_number_key ON quotes (quote_number)"))
