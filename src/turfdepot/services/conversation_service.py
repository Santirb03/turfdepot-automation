"""Deterministic conversation with durable state and message deduplication."""
import re
import unicodedata
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from turfdepot.db.models import Conversation, ConversationMessage, Quote
from turfdepot.schemas.conversation import MessageCreate
from turfdepot.schemas.quote import QuoteCreate
from turfdepot.services.catalog import MODELS
from turfdepot.services.pdf_service import quote_pdf
from turfdepot.services.pricing import PricingNotConfigured
from turfdepot.services.quote_service import build_quote


class MessageConflict(ValueError):
    pass


def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.lower().strip())
                   if unicodedata.category(c) != "Mn").rstrip(".!?")


def parse_area(value: str) -> tuple[Decimal, bool] | None:
    value = value.lower().replace(",", ".")
    value = re.sub(r"^(?:es de|son|tiene|mi jardin es de)\s+", "", value.strip())
    number = r"([0-9]+(?:\.[0-9]{1,2})?)"
    units = r"\s*(?:m|metros)?\s*"
    dimensions = re.fullmatch(number + units + r"(?:x|×|por)\s*" + number + units, value)
    direct = re.fullmatch(number + r"\s*(?:m²|m2|metros cuadrados)?", value)
    if dimensions:
        length, width = map(Decimal, dimensions.groups())
        area, confirmation = length * width, True
    elif direct:
        area, confirmation = Decimal(direct.group(1)), False
    else:
        return None
    if not 0 < area <= 1000000 or area != area.quantize(Decimal("0.01")):
        return None
    return area, confirmation


def process_message(session: Session, data: MessageCreate, prices: dict) -> dict:
    phone = data.contact_phone.lstrip("+")
    with session.begin():
        # Serialize even the first message for a contact across workers.
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(current_schema()), hashtext(:phone))"), {"phone": phone})
        previous = session.get(ConversationMessage, (phone, data.message_id))
        if previous:
            if previous.request_text != data.text:
                raise MessageConflict("El identificador del mensaje ya se usó con otro texto.")
            return previous.response
        conversation = session.get(Conversation, phone)
        if conversation is None:
            conversation = Conversation(phone=phone, state="name")
            session.add(conversation)
            reply = "¡Hola! Bienvenido a TurfDepot 🌱 ¿Cuál es tu nombre?"
        elif conversation.state == "name":
            if len(data.text) > 150 or not any(c.isalpha() for c in data.text):
                reply = "¿Cuál es tu nombre? Escribe hasta 150 caracteres."
            else:
                conversation.customer_name = data.text
                conversation.state = "area"
                reply = f"Mucho gusto, {data.text} 🌱 ¿Cuántos metros cuadrados tiene tu jardín? También puedes darme largo por ancho en metros."
        elif conversation.state == "area":
            result = parse_area(data.text)
            if result is None:
                reply = "Dime una superficie válida en m² (por ejemplo, 40) o largo por ancho en metros (por ejemplo, 30 x 22). Usa hasta dos decimales; la superficie debe ser mayor a 0 y hasta 1.000.000 m²."
            else:
                area, confirmation = result
                conversation.square_meters = area
                conversation.state = "confirm_area" if confirmation else "location"
                reply = (f"Entiendo las medidas en metros: equivalen a {area:f} m². ¿Es correcto?"
                         if confirmation else "¿Dónde está tu jardín? Con una ubicación es suficiente.")
        elif conversation.state == "confirm_area":
            answer = normalized(data.text)
            if answer in {"si", "correcto", "es correcto", "ok"}:
                conversation.state = "location"
                reply = "¿Dónde está tu jardín? Con una ubicación es suficiente."
            elif answer in {"no", "incorrecto"}:
                conversation.square_meters = None
                conversation.state = "area"
                reply = "Dime los metros cuadrados o las medidas correctas en metros."
            else:
                reply = "¿Confirmas la superficie? Responde sí o no."
        elif conversation.state == "location":
            if len(data.text) > 300 or not any(c.isalpha() for c in data.text):
                reply = "Escribe la ubicación de tu jardín, hasta 300 caracteres."
            else:
                if any(key not in prices for key, _, _ in MODELS):
                    raise PricingNotConfigured("Se requieren las tarifas de los ocho modelos para completar la conversación.")
                # Legacy quote API needs a model; this internal reference is not
                # a customer selection. The PDF always offers all eight options.
                quote = build_quote(session, QuoteCreate(
                    customer_name=conversation.customer_name, customer_phone=phone,
                    customer_location=data.text, square_meters=conversation.square_meters,
                    garden_type=MODELS[0][0], extras=[]), prices)
                quote_pdf(quote)  # Failure rolls back both quote and completion.
                conversation.location = data.text
                conversation.quote_id = quote.id
                conversation.state = "completed"
                reply = f"¡Listo, {conversation.customer_name}! 🌱 Tu cotización {quote.quote_number} para {conversation.square_meters:f} m² en {data.text} incluye ocho modelos con IVA incluido. La preparación de base aparece por separado si tu jardín la requiere."
        else:
            # The owner handles all conversation after the quote. Empty means
            # no outbound message, including no follow-up PDF.
            reply = ""
        response = {"reply": reply, "state": conversation.state, "quote_id": None,
                    "quote_number": None, "pdf_url": None}
        if conversation.quote_id:
            quote = session.get(Quote, conversation.quote_id)
            response.update(quote_id=quote.id, quote_number=quote.quote_number,
                            pdf_url=f"/quotes/{quote.id}/pdf")
        session.flush()
        session.add(ConversationMessage(phone=phone, message_id=data.message_id,
                                        request_text=data.text, response=response))
    return response
