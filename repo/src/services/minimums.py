"""Deterministic safety net for ensuring minimum model metadata."""

from __future__ import annotations

import json
from typing import Any

_NUMERIC_TYPES = {
    "int",
    "integer",
    "bigint",
    "float",
    "double",
    "decimal",
    "numeric",
}


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def _first_key_columns(keys_value: Any) -> list[str]:
    if not isinstance(keys_value, list):
        return []
    for entry in keys_value:
        if not isinstance(entry, dict):
            continue
        columns = entry.get("columns")
        if isinstance(columns, list) and columns:
            coerced = [str(column).strip() for column in columns if str(column).strip()]
            if coerced:
                return coerced
    return []


def _ensure_attribute_list(entity: dict[str, Any]) -> list[dict[str, Any]]:
    attributes = entity.get("attributes")
    if isinstance(attributes, list):
        sanitized: list[dict[str, Any]] = []
        for attribute in attributes:
            if isinstance(attribute, dict):
                sanitized.append(attribute)
        if sanitized is not attributes:
            entity["attributes"] = sanitized
        return sanitized
    entity["attributes"] = []
    return entity["attributes"]


def _ensure_identifier_attribute(entity: dict[str, Any], name: str) -> dict[str, Any]:
    attributes = _ensure_attribute_list(entity)
    for attribute in attributes:
        if str(attribute.get("name") or "").strip().lower() == name.lower():
            return attribute
    attribute = {
        "name": name,
        "data_type": "string",
        "semantic_type": "identifier",
        "required": True,
        "is_nullable": False,
        "is_measure": False,
        "is_surrogate_key": False,
    }
    attributes.append(attribute)
    return attribute


def _ensure_measure_attribute(entity: dict[str, Any]) -> bool:
    attributes = _ensure_attribute_list(entity)
    for attribute in attributes:
        if bool(attribute.get("is_measure")):
            return False
    for attribute in attributes:
        data_type = str(attribute.get("data_type") or attribute.get("datatype") or "").lower()
        if data_type in _NUMERIC_TYPES:
            attribute["is_measure"] = True
            attribute.setdefault("semantic_type", "measure")
            if "is_nullable" not in attribute:
                attribute["is_nullable"] = False
            if "required" not in attribute:
                attribute["required"] = True
            return True
    suffix = 1
    existing_names = {str(attr.get("name") or "").strip() for attr in attributes}
    measure_name = "record_count"
    while measure_name in existing_names:
        suffix += 1
        measure_name = f"record_count_{suffix}"
    attributes.append(
        {
            "name": measure_name,
            "data_type": "int",
            "semantic_type": "measure",
            "required": True,
            "is_nullable": False,
            "is_measure": True,
            "is_surrogate_key": False,
        }
    )
    return True


def enforce_minimums(model_json_str: str) -> str:
    """Fill required fact grain/measure and dimension SCD metadata when absent."""

    try:
        payload = json.loads(model_json_str)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError("Model JSON is not valid.") from exc

    if not isinstance(payload, dict):
        raise ValueError("Model JSON must be a JSON object.")

    entities = payload.get("entities")
    if not isinstance(entities, list):
        return model_json_str

    changed = False
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        role = str(entity.get("role") or "").strip().lower()
        name = str(entity.get("name") or "").strip() or "fact"
        if role == "fact":
            grain = _coerce_list(entity.get("grain_json")) or _coerce_list(entity.get("grain"))
            if not grain:
                candidates = [
                    str(attr.get("name")).strip()
                    for attr in _ensure_attribute_list(entity)
                    if isinstance(attr, dict)
                    and str(attr.get("name") or "").strip().endswith("_id")
                ]
                if not candidates:
                    candidates = _first_key_columns(entity.get("keys"))
                if not candidates:
                    identifier = _ensure_identifier_attribute(entity, f"{name.lower()}_id")
                    candidates = [str(identifier.get("name"))]
                entity["grain_json"] = candidates
                changed = True
            else:
                entity["grain_json"] = grain
            if _ensure_measure_attribute(entity):
                changed = True
        elif role == "dimension":
            scd_type = str(entity.get("scd_type") or "").strip().lower()
            if scd_type not in {"none", "scd1", "scd2"}:
                entity["scd_type"] = "scd1"
                changed = True

    if changed:
        return json.dumps(payload, ensure_ascii=False)
    return model_json_str


__all__ = ["enforce_minimums"]
