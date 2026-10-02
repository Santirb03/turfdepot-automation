from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from turfdepot.api.routes import health, quotes
from turfdepot.core.config import Settings
from turfdepot.db.models import Base


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine(settings.connection_url(), pool_pre_ping=True,
                           connect_args={"connect_timeout": 5})

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            # Initial MVP schema only; create_all does not migrate existing tables.
            Base.metadata.create_all(engine)
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="TurfDepot Sales & Quote Automation Platform", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.include_router(health.router)
    app.include_router(quotes.router)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Never expose SQL statements, customer data, or connection credentials.
        return JSONResponse(status_code=503, content={"detail": "Base de datos no disponible."})

    return app
