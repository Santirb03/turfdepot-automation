import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert

from turfdepot.api.routes.quotes import DatabaseSession
from turfdepot.db.models import WhatsAppJob
from turfdepot.schemas.conversation import MessageCreate

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])
MAX_BODY = 1024 * 1024


@router.get("", response_class=PlainTextResponse)
def verify(request: Request):
    settings = request.app.state.settings
    if not settings.whatsapp_enabled:
        raise HTTPException(503, "WhatsApp no está habilitado.")
    query = request.query_params
    token = settings.whatsapp_verify_token.get_secret_value().encode()
    if (query.get("hub.mode") != "subscribe" or not query.get("hub.challenge")
            or not hmac.compare_digest(query.get("hub.verify_token", "").encode(), token)):
        raise HTTPException(403, "Verificación inválida.")
    return query["hub.challenge"]


def incoming_jobs(payload: dict, phone_number_id: str) -> list[dict]:
    if payload.get("object") != "whatsapp_business_account":
        return []
    jobs = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if change.get("field") != "messages" or value.get("metadata", {}).get("phone_number_id") != phone_number_id:
                continue
            for message in value.get("messages", []):
                if not isinstance(message.get("timestamp"), str) or not message["timestamp"].isdigit():
                    raise ValueError("Invalid timestamp")
                inbound_at = datetime.fromtimestamp(int(message["timestamp"]), timezone.utc)
                body = message.get("text", {}).get("body") if message.get("type") == "text" else None
                # Unsupported content is acknowledged and answered without advancing state.
                if not isinstance(body, str) or not body.strip() or len(body.strip()) > 1000:
                    body = None
                identity = MessageCreate(contact_phone=message["from"], message_id=message["id"], text=body or "unsupported")
                jobs.append(dict(message_id=identity.message_id, phone=identity.contact_phone.lstrip("+"),
                                 message_text=body.strip() if body else None, inbound_at=inbound_at, status="pending"))
    return jobs


@router.post("")
async def receive(request: Request, session: DatabaseSession):
    settings = request.app.state.settings
    if not settings.whatsapp_enabled:
        raise HTTPException(503, "WhatsApp no está habilitado.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            raise HTTPException(413, "Webhook demasiado grande.")
    expected = "sha256=" + hmac.new(settings.whatsapp_app_secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("x-hub-signature-256", "").encode(), expected.encode()):
        raise HTTPException(403, "Firma inválida.")
    try:
        payload = json.loads(body)
        jobs = incoming_jobs(payload, settings.whatsapp_phone_number_id)
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, ValidationError) as exc:
        raise HTTPException(400, "Webhook inválido.") from exc
    with session.begin():
        for job in jobs:
            session.execute(insert(WhatsAppJob).values(**job).on_conflict_do_nothing(index_elements=["message_id"]))
    return {"status": "received"}
