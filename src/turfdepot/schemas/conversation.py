from typing import Literal

from pydantic import Field
from turfdepot.schemas.quote import InputModel


class MessageCreate(InputModel):
    contact_phone: str = Field(pattern=r"^\+?[0-9]{7,15}$")
    message_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=1000)


class MessageRead(InputModel):
    reply: str
    state: Literal["name", "area", "confirm_area", "location", "completed"]
    quote_id: int | None = None
    quote_number: int | None = None
    pdf_url: str | None = None
