from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_telegram_ids_raw: str = Field(default="", alias="ADMIN_TELEGRAM_IDS")
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    marzban_base_url: str = Field(alias="MARZBAN_BASE_URL")
    marzban_username: str = Field(alias="MARZBAN_USERNAME")
    marzban_password: str = Field(alias="MARZBAN_PASSWORD")
    marzban_token: str | None = Field(default=None, alias="MARZBAN_TOKEN")
    marzban_inbound_id_or_profile: str = Field(default="3", alias="MARZBAN_INBOUND_ID_OR_PROFILE")
    marzban_subscription_base_url: str | None = Field(
        default=None, alias="MARZBAN_SUBSCRIPTION_BASE_URL"
    )

    price_per_gb_toman: int = Field(default=220_000, alias="PRICE_PER_GB_TOMAN")
    min_custom_gb: int = Field(default=1, alias="MIN_CUSTOM_GB")
    max_custom_gb: int = Field(default=1000, alias="MAX_CUSTOM_GB")

    card_number: str = Field(default="", alias="CARD_NUMBER")
    card_holder_name: str = Field(default="", alias="CARD_HOLDER_NAME")
    bank_name: str = Field(default="", alias="BANK_NAME")
    support_username: str = Field(default="", alias="SUPPORT_USERNAME")

    default_language: str = Field(default="fa", alias="DEFAULT_LANGUAGE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def admin_telegram_ids(self) -> list[int]:
        if not self.admin_telegram_ids_raw:
            return []
        return [int(item.strip()) for item in self.admin_telegram_ids_raw.split(",") if item.strip()]

    @field_validator("default_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return value if value in {"fa", "en"} else "fa"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
