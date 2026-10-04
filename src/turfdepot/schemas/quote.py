from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ExtraCreate(InputModel):
    name: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2, allow_inf_nan=False)


class QuoteCreate(InputModel):
    customer_name: str = Field(min_length=1, max_length=150)
    customer_phone: str = Field(min_length=7, max_length=30, pattern=r"^\+?[0-9 ()-]+$")
    customer_location: str = Field(min_length=1, max_length=300)
    square_meters: Decimal = Field(gt=0, le=1000000, decimal_places=2, allow_inf_nan=False)
    garden_type: str = Field(min_length=1, max_length=80)
    extras: list[ExtraCreate] = Field(default_factory=list, max_length=100)

    @field_validator("customer_phone")
    @classmethod
    def phone_has_digits(cls, phone: str) -> str:
        if not 7 <= sum(character.isdigit() for character in phone) <= 15:
            raise ValueError("El teléfono debe contener entre 7 y 15 dígitos.")
        return phone


class QuoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quote_number: int
    customer_id: int
    square_meters: Decimal
    garden_type: str
    subtotal: Decimal
    extras_total: Decimal
    total: Decimal
    status: Literal["pending"]
    created_at: datetime
