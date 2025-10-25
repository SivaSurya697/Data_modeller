"""Application configuration helpers."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field


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
