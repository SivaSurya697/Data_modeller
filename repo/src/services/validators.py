"""Pydantic models shared across blueprints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class UserSettingsInput(BaseModel):
    """Validate persisted user configuration."""

    openai_api_key: str = Field(min_length=1)
    openai_base_url: str = Field(min_length=1, max_length=255)
    rate_limit_per_minute: int = Field(gt=0)


class DomainInput(BaseModel):
    """Validate domain creation input."""

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)


class DraftRequest(BaseModel):
    """Validate requests for new model drafts."""

    domain_id: int
    instructions: str | None = None


class ChangeSetInput(BaseModel):
    """Validate change-set submissions."""

    domain_id: int
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)


class ExportRequest(BaseModel):
    """Validate export requests."""

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


class CoverageAnalysisRequest(BaseModel):
    """Validate coverage analysis requests."""

    domain_id: int = Field(gt=0)


__all__ = [
    "ChangeSetInput",
    "CoverageAnalysisRequest",
    "DomainInput",
    "DraftRequest",
    "ExportRequest",
    "UserSettingsInput",
]

