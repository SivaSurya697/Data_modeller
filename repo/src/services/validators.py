"""Pydantic models shared across blueprints and deterministic checks."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.tables import EntityRole, SCDType

_SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_DATA_TYPES = {
    "string",
    "text",
    "varchar",
    "int",
    "integer",
    "bigint",
    "float",
    "double",
    "decimal",
    "numeric",
    "boolean",
    "date",
    "datetime",
    "timestamp",
}
_ALLOWED_RELATIONSHIP_TYPES = {
    "one_to_one",
    "one_to_many",
    "many_to_one",
    "many_to_many",
}
_DIMENSION_KEY_TYPES = {"business", "natural", "primary"}
_ALLOWED_SCD_TYPES = {"none", "scd1", "scd2"}


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


class CoverageAnalysisRequest(BaseModel):
    """Validate coverage analysis requests."""

    domain_id: int


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


def is_snake_case(name: str) -> bool:
    """Return ``True`` when ``name`` follows ``snake_case`` conventions."""

    if not isinstance(name, str):
        return False
    return bool(_SNAKE_CASE_PATTERN.fullmatch(name.strip()))


def allowed_datatype(data_type: str | None) -> bool:
    """Return whether ``data_type`` is part of the allowlist."""

    if data_type is None:
        return True
    return data_type.strip().lower() in _ALLOWED_DATA_TYPES


def validate_model_json(model_json_str: str) -> dict[str, Any]:
    """Validate deterministic dimensional modelling rules."""

    issues: list[str] = []
    try:
        payload = json.loads(model_json_str)
    except json.JSONDecodeError as exc:
        return {"ok": False, "issues": [f"Invalid JSON payload: {exc.msg}"]}

    entities_raw = payload.get("entities")
    if not isinstance(entities_raw, list):
        issues.append("Model must include an 'entities' array.")
        entities_raw = []

    for entity in entities_raw:
        if not isinstance(entity, dict):
            issues.append("Entities must be objects containing metadata.")
            continue

        entity_name_raw = entity.get("name")
        if not isinstance(entity_name_raw, str) or not entity_name_raw.strip():
            issues.append("Entities must define a non-empty 'name'.")
            continue
        entity_name = entity_name_raw.strip()
        if not is_snake_case(entity_name):
            issues.append(f"Entity '{entity_name}' name must be snake_case.")

        role_value = str(entity.get("role") or "").strip().lower()
        attributes_raw = entity.get("attributes")
        if not isinstance(attributes_raw, list):
            issues.append(f"Entity '{entity_name}' must include an 'attributes' array.")
            attributes_raw = []

        attribute_names: set[str] = set()
        has_measure = False

        for attribute in attributes_raw:
            if not isinstance(attribute, dict):
                issues.append(
                    f"Entity '{entity_name}' has an attribute entry that is not an object."
                )
                continue

            attr_name_raw = attribute.get("name")
            if not isinstance(attr_name_raw, str) or not attr_name_raw.strip():
                issues.append(f"Entity '{entity_name}' has an attribute without a name.")
                continue
            attr_name = attr_name_raw.strip()
            attribute_names.add(attr_name)
            if not is_snake_case(attr_name):
                issues.append(
                    f"Attribute '{entity_name}.{attr_name}' name must be snake_case."
                )

            data_type_value = attribute.get("data_type")
            if data_type_value is not None and not allowed_datatype(str(data_type_value)):
                issues.append(
                    f"Attribute '{entity_name}.{attr_name}' uses disallowed data type '{data_type_value}'."
                )

            if bool(attribute.get("is_measure")):
                has_measure = True

        grain_value = entity.get("grain_json")
        if grain_value is None:
            grain_value = entity.get("grain")

        grain_items: Iterable[str]
        if isinstance(grain_value, str):
            grain_items = [grain_value]
        elif isinstance(grain_value, Iterable) and not isinstance(grain_value, (bytes, dict)):
            grain_items = [str(item) for item in grain_value]
        else:
            grain_items = []

        if role_value == EntityRole.FACT.value:
            if not list(grain_items):
                issues.append(f"Fact '{entity_name}' must define a non-empty grain.")
            if not has_measure:
                issues.append(f"Fact '{entity_name}' must include at least one measure.")

        keys_value = entity.get("keys")
        if keys_value is not None and not isinstance(keys_value, list):
            issues.append(f"Entity '{entity_name}' keys must be an array when provided.")
            keys_value = []

        has_dimension_key = False
        if isinstance(keys_value, list):
            for entry in keys_value:
                if not isinstance(entry, dict):
                    issues.append(
                        f"Entity '{entity_name}' has a key entry that is not an object."
                    )
                    continue
                key_type = str(entry.get("type") or "").strip().lower()
                columns_raw = entry.get("columns")
                if not isinstance(columns_raw, list) or not columns_raw:
                    issues.append(
                        f"Entity '{entity_name}' key '{key_type or 'unknown'}' must list at least one column."
                    )
                    continue
                missing = [
                    str(column)
                    for column in columns_raw
                    if str(column) not in attribute_names
                ]
                if missing:
                    issues.append(
                        f"Entity '{entity_name}' key '{key_type or 'unknown'}' references unknown columns: {', '.join(missing)}."
                    )
                if key_type in _DIMENSION_KEY_TYPES and not missing:
                    has_dimension_key = True
        if role_value == EntityRole.DIMENSION.value:
            scd_value = str(entity.get("scd_type") or "").strip().lower()
            if scd_value not in _ALLOWED_SCD_TYPES:
                issues.append(
                    f"Dimension '{entity_name}' must declare an SCD type of 'none', 'scd1', or 'scd2'."
                )
            if not has_dimension_key:
                issues.append(
                    f"Dimension '{entity_name}' must define a business, natural, or primary key."
                )

    relationships_value = payload.get("relationships")
    if relationships_value is not None and not isinstance(relationships_value, list):
        issues.append("'relationships' must be an array when provided.")
        relationships_value = []

    if isinstance(relationships_value, list):
        for relationship in relationships_value:
            if not isinstance(relationship, dict):
                issues.append("Relationships must be objects containing metadata.")
                continue
            rel_type = str(relationship.get("type") or "").strip().lower()
            if rel_type and rel_type not in _ALLOWED_RELATIONSHIP_TYPES:
                issues.append(
                    f"Relationship '{relationship}' has an unsupported type '{rel_type}'."
                )

    return {"ok": not issues, "issues": issues}


def quality_summary(
    model_json_str: str,
    mappings: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return aggregate quality metrics for a model."""

    try:
        payload = json.loads(model_json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc.msg}") from exc

    entities = payload.get("entities")
    if not isinstance(entities, list):
        entities = []

    facts = []
    dimensions = []
    required_attribute_records: list[tuple[int | None, str]] = []
    key_membership: dict[str, set[str]] = defaultdict(set)

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        role_value = str(entity.get("role") or "").strip().lower()
        name_value = str(entity.get("name") or "").strip()
        if role_value == EntityRole.FACT.value:
            facts.append(name_value)
        elif role_value == EntityRole.DIMENSION.value:
            dimensions.append(entity)

        attributes = entity.get("attributes")
        if not isinstance(attributes, list):
            continue

        keys_value = entity.get("keys")
        if isinstance(keys_value, list):
            for entry in keys_value:
                if not isinstance(entry, dict):
                    continue
                columns = entry.get("columns")
                if isinstance(columns, list):
                    for column in columns:
                        key_membership[name_value].add(str(column))

        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            attr_name = str(attribute.get("name") or "").strip()
            attr_id = attribute.get("id")
            if attr_id is not None:
                try:
                    attr_id = int(attr_id)
                except (TypeError, ValueError):
                    attr_id = None

            is_required = bool(attribute.get("required"))
            if not is_required and "is_nullable" in attribute:
                is_required = not bool(attribute.get("is_nullable", True))
            if not is_required and bool(attribute.get("is_measure")):
                is_required = True
            if not is_required and attr_name and attr_name in key_membership.get(name_value, set()):
                is_required = True

            if is_required:
                required_attribute_records.append((attr_id, attr_name))

    mapping_pct: float | None
    if mappings is None:
        mapping_pct = None
    else:
        allowed_statuses = {"approved", "draft"}
        mapped_attribute_ids = {
            int(mapping["attribute_id"])
            for mapping in mappings
            if isinstance(mapping, dict)
            and mapping.get("attribute_id") is not None
            and str(mapping.get("status") or "").strip().lower() in allowed_statuses
        }
        required_count = len(required_attribute_records)
        if required_count == 0:
            mapping_pct = 1.0
        else:
            required_ids = {attr_id for attr_id, _ in required_attribute_records if attr_id is not None}
            if required_ids:
                covered = len(required_ids & mapped_attribute_ids)
            else:
                covered = min(len(mapped_attribute_ids), required_count)
            mapping_pct = covered / required_count

    if relationships is None:
        rel_coverage_pct = None
    else:
        fact_names = [name for name in facts if name]
        fact_set = set(fact_names)
        dim_names = {
            str(dimension.get("name") or "").strip()
            for dimension in dimensions
            if isinstance(dimension, dict)
        }
        covered_facts: set[str] = set()
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            from_name = str(
                relationship.get("from")
                or relationship.get("source")
                or relationship.get("from_entity")
                or ""
            ).strip()
            to_name = str(
                relationship.get("to")
                or relationship.get("target")
                or relationship.get("to_entity")
                or ""
            ).strip()

            if from_name in fact_set and to_name in dim_names:
                covered_facts.add(from_name)
            if to_name in fact_set and from_name in dim_names:
                covered_facts.add(to_name)

        if not fact_names:
            rel_coverage_pct = 1.0
        else:
            rel_coverage_pct = len(covered_facts) / len(fact_names)

    mece_score = 1.0
    facts_count = len(facts)
    dim_list = [dimension for dimension in dimensions if isinstance(dimension, dict)]
    if not dim_list:
        dims_scd_pct = 1.0
    else:
        valid_dims = 0
        for dimension in dim_list:
            scd_value = str(dimension.get("scd_type") or "").strip().lower()
            if scd_value in _ALLOWED_SCD_TYPES:
                valid_dims += 1
        dims_scd_pct = valid_dims / len(dim_list)

    return {
        "mapping_pct": mapping_pct,
        "rel_coverage_pct": rel_coverage_pct,
        "mece_score": mece_score,
        "facts_count": facts_count,
        "dims_scd_pct": dims_scd_pct,
    }


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
    "allowed_datatype",
    "is_snake_case",
    "quality_summary",
    "validate_model_json",
]

