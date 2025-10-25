"""Application configuration helpers."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.tables import Setting

OPENAI_API_KEY_KEYS: tuple[str, ...] = (
    "openai_api_key",
    "openai.api_key",
)
OPENAI_BASE_URL_KEYS: tuple[str, ...] = (
    "openai_base_url",
    "openai.base_url",
)


class AppSettings(BaseModel):
    """Central application settings loaded from the environment."""

    environment: str = Field(default="production")
    database_url: str = Field(default="sqlite:///data_modeller.db")
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    rate_limit_per_minute: int = Field(default=60)

    @property
    def openai_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments needed to configure the OpenAI client."""

        return {
            "api_key": self.openai_api_key,
            "base_url": self.openai_base_url,
        }


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    """Load and cache application settings."""

    return AppSettings(
        environment=os.getenv("FLASK_ENV", "production"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///data_modeller.db"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
    )


def _resolve_setting(
    records: dict[str, str],
    user_id: int,
    *aliases: str,
) -> str | None:
    """Resolve a stored setting taking optional user overrides into account."""

    user_prefix = f"user:{user_id}:"
    lookup_order = [f"{user_prefix}{alias}".lower() for alias in aliases]
    lookup_order.extend(alias.lower() for alias in aliases)
    for key in lookup_order:
        value = records.get(key)
        if value:
            return value.strip()
    return None


def load_openai_credentials(db: Session, user_id: int) -> tuple[str, str]:
    """Load OpenAI credentials, checking persisted overrides before fallbacks."""

    settings = load_settings()
    stored = {
        record.key.strip().lower(): record.value.strip()
        for record in db.execute(select(Setting)).scalars()
    }

    api_key = _resolve_setting(stored, user_id, *OPENAI_API_KEY_KEYS) or settings.openai_api_key
    base_url = _resolve_setting(stored, user_id, *OPENAI_BASE_URL_KEYS) or settings.openai_base_url

    api_key = api_key.strip()
    base_url = base_url.strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    if not base_url:
        base_url = settings.openai_base_url
    return api_key, base_url
