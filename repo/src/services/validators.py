"""Pydantic models shared across blueprints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.tables import EntityRole, SCDType


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


class AttributeSpec(BaseModel):
    """Validate LLM-proposed attribute metadata."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str = Field(min_length=1)
    data_type: str | None = None
    description: str | None = None
    is_nullable: bool = True
    default: str | None = Field(default=None, alias="default")
    is_measure: bool
    is_surrogate_key: bool


class EntitySpec(BaseModel):
    """Validate LLM-proposed entity metadata."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    description: str | None = None
    documentation: str | None = None
    role: EntityRole
    grain: list[str] = Field(min_length=1)
    scd_type: SCDType
    attributes: list[AttributeSpec] = Field(min_length=1)

    @field_validator("grain", mode="before")
    @classmethod
    def ensure_grain(cls, value: Any) -> list[str]:
        if value is None:
            raise ValueError("grain is required")
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple)):
            items = list(value)
        else:
            raise TypeError("grain must be a list of attribute names")
        result: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                raise ValueError("grain values must be non-empty strings")
            result.append(text)
        return result


class ModelDraftPayload(BaseModel):
    """Validate the full payload returned by the LLM."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    summary: str | None = None
    definition: str | None = None
    entities: list[EntitySpec] = Field(min_length=1)


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


class SourceColumnInput(BaseModel):
    """Validate column metadata supplied during source imports."""

    name: str = Field(min_length=1, max_length=255)
    data_type: str | None = Field(default=None, max_length=255)
    is_nullable: bool = True
    ordinal_position: int | None = Field(default=None, ge=1)
    description: str | None = None
    statistics: dict[str, Any] | None = None
    sample_values: list[Any] | None = None


class SourceTableInput(BaseModel):
    """Validate table metadata supplied during source imports."""

    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(min_length=1, max_length=255)
    table_name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    schema_definition: dict[str, Any] | None = Field(default=None, alias="schema")
    table_statistics: dict[str, Any] | None = Field(
        default=None, alias="statistics"
    )
    row_count: int | None = Field(default=None, ge=0)
    sampled_row_count: int | None = Field(default=None, ge=0)
    profiled_at: datetime | None = None
    columns: list[SourceColumnInput] = Field(default_factory=list)

    @field_validator("columns")
    @classmethod
    def ensure_unique_columns(
        cls, value: list[SourceColumnInput]
    ) -> list[SourceColumnInput]:
        seen: set[str] = set()
        for column in value:
            key = column.name.strip().lower()
            if key in seen:
                raise ValueError("Duplicate column name detected")
            seen.add(key)
        return value


class SourceSystemInput(BaseModel):
    """Validate source system metadata."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    connection_type: str = Field(min_length=1, max_length=100)
    connection_config: dict[str, Any] | None = None


class SourceImportRequest(BaseModel):
    """Validate source import requests."""

    system: SourceSystemInput
    tables: list[SourceTableInput] = Field(default_factory=list)


class SourceProfileRequest(BaseModel):
    """Validate profile submissions containing sampled rows."""

    model_config = ConfigDict(populate_by_name=True)

    table_id: int
    samples: list[dict[str, Any]] = Field(default_factory=list, alias="rows")
    total_rows: int | None = Field(default=None, ge=0)


__all__ = [
    "ChangeSetInput",
    "CoverageAnalysisRequest",
    "DomainInput",
    "DraftRequest",
    "AttributeSpec",
    "EntitySpec",
    "ModelDraftPayload",
    "ExportRequest",
    "SourceColumnInput",
    "SourceImportRequest",
    "SourceProfileRequest",
    "SourceSystemInput",
    "SourceTableInput",
    "UserSettingsInput",
]

