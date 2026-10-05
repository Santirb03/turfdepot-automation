from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from turfdepot.api.routes import health, quotes, conversations, whatsapp
from turfdepot.core.config import Settings
from turfdepot.db.schema import initialize_schema


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine(settings.connection_url(), pool_pre_ping=True,
                           connect_args={"connect_timeout": 5})

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            initialize_schema(engine)
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="TurfDepot Sales & Quote Automation Platform", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.include_router(health.router)
    app.include_router(quotes.router)
    app.include_router(conversations.router)
    app.include_router(whatsapp.router)

    @app.middleware("http")
    async def protect_internal_api(request: Request, call_next):
        # Enabling a public webhook must not expose customer/PDF routes.
        if settings.whatsapp_enabled and request.url.path not in {"/health", "/webhooks/whatsapp"}:
            expected = "Bearer " + settings.internal_api_key.get_secret_value()
            if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
                return JSONResponse(status_code=401, content={"detail": "Autenticación requerida."})
        return await call_next(request)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Never expose SQL statements, customer data, or connection credentials.
        return JSONResponse(status_code=503, content={"detail": "Base de datos no disponible."})

    return app
