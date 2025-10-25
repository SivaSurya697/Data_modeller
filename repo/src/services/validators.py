"""Form validation schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SettingsInput(BaseModel):
    """Validate persisted connection and LLM configuration."""

    api_key: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=255)
    model_name: str | None = Field(default=None, max_length=255)


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

    domain_id: int
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)


class ExportRequest(BaseModel):
    """Validate export request input."""

    domain_id: int
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
