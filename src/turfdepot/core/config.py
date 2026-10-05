from decimal import Decimal
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from turfdepot.services.catalog import approved_prices

Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2, allow_inf_nan=False)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = None
    db_host: str = "localhost"
    db_user: str = "turfdepot"
    db_password: str | None = None
    db_name: str = "turfdepot"
    garden_prices: dict[str, Price] = Field(default_factory=approved_prices)
    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str = Field(default="", pattern=r"^[0-9]*$")
    whatsapp_api_version: str = Field(default="", pattern=r"^(?:v[0-9]+\.[0-9]+)?$")
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_verify_token: SecretStr = SecretStr("")
    internal_api_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def whatsapp_configuration(self):
        if self.whatsapp_enabled:
            if not self.whatsapp_phone_number_id or not self.whatsapp_api_version:
                raise ValueError("Configure WHATSAPP_PHONE_NUMBER_ID y WHATSAPP_API_VERSION.")
            for name in ("whatsapp_access_token", "whatsapp_app_secret", "whatsapp_verify_token", "internal_api_key"):
                if not getattr(self, name).get_secret_value().strip():
                    raise ValueError(f"Configure {name.upper()} antes de habilitar WhatsApp.")
        return self

    @field_validator("garden_prices")
    @classmethod
    def validate_keys(cls, prices: dict[str, Decimal]) -> dict[str, Decimal]:
        if any(not key.strip() or key != key.strip() or len(key) > 80 for key in prices):
            raise ValueError("Garden types must be nonempty trimmed strings of at most 80 characters")
        return prices

    def connection_url(self) -> URL:
        if self.database_url:
            url = make_url(self.database_url)
            if url.drivername not in {"postgresql", "postgresql+psycopg"}:
                raise ValueError("DATABASE_URL must use PostgreSQL with psycopg")
            return url.set(drivername="postgresql+psycopg")
        if not self.db_password:
            raise ValueError("Configure DATABASE_URL or DB_PASSWORD")
        return URL.create("postgresql+psycopg", username=self.db_user,
                          password=self.db_password, host=self.db_host, database=self.db_name)
