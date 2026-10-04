from fastapi import APIRouter, HTTPException, Request

from turfdepot.api.routes.quotes import DatabaseSession
from turfdepot.schemas.conversation import MessageCreate, MessageRead
from turfdepot.services.conversation_service import MessageConflict, process_message
from turfdepot.services.pdf_service import PdfUnavailable
from turfdepot.services.pricing import PricingNotConfigured

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/messages", response_model=MessageRead)
def receive_message(data: MessageCreate, request: Request, session: DatabaseSession):
    try:
        return process_message(session, data, request.app.state.settings.garden_prices)
    except MessageConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PricingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PdfUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
