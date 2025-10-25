"""Form validation schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class UserSettingsPayload(BaseModel):
    """Validate API payloads for user settings updates."""

    openai_api_key: str | None = Field(default=None)
    openai_base_url: str | None = Field(default=None)

    @field_validator("openai_api_key", "openai_base_url", mode="before")
    @classmethod
    def _normalise(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        return value

    @model_validator(mode="after")
    def _ensure_payload_not_empty(self) -> "UserSettingsPayload":
        if self.openai_api_key is None and self.openai_base_url is None:
            raise ValueError("At least one setting must be provided")
        return self


class DomainInput(BaseModel):
    """Validate domain creation input."""

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)


class DraftRequest(BaseModel):
    """Validate requests for new model drafts."""

    domain_id: int
    instructions: str | None = None


class ChangeSetInput(BaseModel):
    """Validate changeset form submissions."""

    model_id: int
    description: str = Field(min_length=1)


class ExportRequest(BaseModel):
    """Validate export request input."""

    model_id: int
    exporter: str

    @field_validator("exporter")
    @classmethod
    def ensure_known_exporter(cls, value: str) -> str:
        allowed: tuple[Literal["dictionary"], Literal["plantuml"]] = (
            "dictionary",
            "plantuml",
        )
        if value not in allowed:
            raise ValueError("Unsupported exporter requested")
        return value
