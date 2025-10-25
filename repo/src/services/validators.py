"""Model definition validation helpers."""
from __future__ import annotations

import json
from json import JSONDecodeError


_ALLOWED_RELATIONSHIP_TYPES = {
    "one_to_one",
    "one_to_many",
    "many_to_one",
    "many_to_many",
}


def _normalise_key_spec(value: object) -> list[str] | None:
    """Normalise a primary key specification into a list of strings."""

    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, list):
        keys: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                keys.append(item.strip())
            else:
                return None
        return keys
    return None


def _extract_attribute_name(attribute: object) -> str | None:
    if not isinstance(attribute, dict):
        return None
    name = attribute.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _relationship_endpoint(relationship: dict[str, object], key: str) -> str | None:
    value = relationship.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    alt_key = f"{key}_entity"
    value = relationship.get(alt_key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    nested = relationship.get(key.replace("_entity", ""))
    if isinstance(nested, dict):
        nested_value = nested.get("entity")
        if isinstance(nested_value, str) and nested_value.strip():
            return nested_value.strip()
    return None


def _relationship_attribute(relationship: dict[str, object], key: str) -> str | None:
    value = relationship.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    nested = relationship.get(key.replace("_attribute", ""))
    if isinstance(nested, dict):
        nested_value = nested.get("attribute") or nested.get("key")
        if isinstance(nested_value, str) and nested_value.strip():
            return nested_value.strip()
    return None


def validate_model_json(model_json_str: str) -> dict[str, object]:
    """Validate a model definition provided as JSON.

    The JSON is expected to describe entities, their attributes, and optional
    relationships between entities. Rather than failing fast, the function
    accumulates all detected issues to present a comprehensive report back to
    the caller. Ordering of the issues is deterministic and follows the order
    in which problems are discovered while walking the payload.
    """

    issues: list[str] = []
    try:
        payload = json.loads(model_json_str)
    except JSONDecodeError as exc:  # pragma: no cover - defensive clarity
        message = f"Invalid JSON: {exc.msg} (line {exc.lineno} column {exc.colno})"
        return {"ok": False, "issues": [message]}

    if not isinstance(payload, dict):
        issues.append("Top-level JSON value must be an object with 'entities'.")
        return {"ok": False, "issues": issues}

    raw_entities = payload.get("entities")
    if not isinstance(raw_entities, list) or not raw_entities:
        issues.append("'entities' must be a non-empty list.")
        return {"ok": False, "issues": issues}

    entity_attributes: dict[str, set[str]] = {}

    for index, entity in enumerate(raw_entities):
        entity_label = f"Entity {index + 1}"
        if not isinstance(entity, dict):
            issues.append(f"{entity_label} must be an object.")
            continue

        name_raw = entity.get("name")
        if not isinstance(name_raw, str) or not name_raw.strip():
            issues.append(f"{entity_label} is missing a valid 'name'.")
            continue
        name = name_raw.strip()
        if name in entity_attributes:
            issues.append(f"Duplicate entity name detected: '{name}'.")
            continue
        raw_attributes = entity.get("attributes")
        if not isinstance(raw_attributes, list) or not raw_attributes:
            issues.append(f"{name}: 'attributes' must be a non-empty list.")
            continue

        seen_attributes: set[str] = set()
        for attr_index, attribute in enumerate(raw_attributes):
            attr_label = f"{name} attribute {attr_index + 1}"
            attr_name = _extract_attribute_name(attribute)
            if attr_name is None:
                issues.append(f"{attr_label} is missing a valid 'name'.")
                continue
            if attr_name in seen_attributes:
                issues.append(
                    f"{name}: duplicate attribute name '{attr_name}' detected."
                )
                continue
            seen_attributes.add(attr_name)
        if not seen_attributes:
            issues.append(f"{name}: no valid attributes defined.")
            continue
        entity_attributes[name] = seen_attributes

        primary_key = _normalise_key_spec(entity.get("primary_key"))
        if primary_key is None or not primary_key:
            issues.append(f"{name}: 'primary_key' must reference one or more attributes.")
        else:
            missing_keys = [key for key in primary_key if key not in seen_attributes]
            if missing_keys:
                formatted = ", ".join(sorted(missing_keys))
                issues.append(
                    f"{name}: primary key references unknown attributes: {formatted}."
                )

    raw_relationships = payload.get("relationships")
    if raw_relationships is None:
        return {"ok": not issues, "issues": issues}

    if not isinstance(raw_relationships, list):
        issues.append("'relationships' must be a list if provided.")
        return {"ok": not issues, "issues": issues}

    for index, relationship in enumerate(raw_relationships):
        rel_label = f"Relationship {index + 1}"
        if not isinstance(relationship, dict):
            issues.append(f"{rel_label} must be an object.")
            continue

        rel_type = relationship.get("type")
        if not isinstance(rel_type, str) or rel_type.strip() not in _ALLOWED_RELATIONSHIP_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_RELATIONSHIP_TYPES))
            issues.append(
                f"{rel_label} has invalid 'type'. Expected one of: {allowed}."
            )

        source_entity = _relationship_endpoint(relationship, "from")
        if source_entity is None:
            issues.append(f"{rel_label} is missing a valid source entity reference.")
        elif source_entity not in entity_attributes:
            issues.append(
                f"{rel_label} references unknown source entity '{source_entity}'."
            )

        target_entity = _relationship_endpoint(relationship, "to")
        if target_entity is None:
            issues.append(f"{rel_label} is missing a valid target entity reference.")
        elif target_entity not in entity_attributes:
            issues.append(
                f"{rel_label} references unknown target entity '{target_entity}'."
            )

        source_attribute = _relationship_attribute(relationship, "from_attribute")
        if source_attribute and source_entity in entity_attributes:
            if source_attribute not in entity_attributes[source_entity]:
                issues.append(
                    f"{rel_label}: source attribute '{source_attribute}' not found on '{source_entity}'."
                )

        target_attribute = _relationship_attribute(relationship, "to_attribute")
        if target_attribute and target_entity in entity_attributes:
            if target_attribute not in entity_attributes[target_entity]:
                issues.append(
                    f"{rel_label}: target attribute '{target_attribute}' not found on '{target_entity}'."
                )

    return {"ok": not issues, "issues": issues}
