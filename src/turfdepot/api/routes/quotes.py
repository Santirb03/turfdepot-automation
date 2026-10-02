from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.orm import Session

from turfdepot.db.database import get_session
from turfdepot.db.models import Quote
from turfdepot.schemas.quote import QuoteCreate, QuoteRead
from turfdepot.services import quote_service
from turfdepot.services.pricing import PricingNotConfigured, UnknownGardenType

router = APIRouter(prefix="/quotes", tags=["quotes"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.post("", response_model=QuoteRead, status_code=201)
def create_quote(data: QuoteCreate, request: Request, session: DatabaseSession) -> Quote:
    try:
        return quote_service.create_quote(session, data, request.app.state.settings.garden_prices)
    except PricingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnknownGardenType as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{id}", response_model=QuoteRead)
def get_quote(id: Annotated[int, Path(gt=0, le=2147483647)], session: DatabaseSession) -> Quote:
    quote = quote_service.get_quote(session, id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Cotización no encontrada.")
    return quote
