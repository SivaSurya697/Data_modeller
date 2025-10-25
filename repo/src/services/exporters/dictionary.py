"""Render a markdown data dictionary from a JSON model payload."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_BOOL_TRUE = {"true", "yes", "y", "1"}
_BOOL_FALSE = {"false", "no", "n", "0"}


def emit_dictionary_md(model_json_str: str, out_path: str) -> Path:
    """Write a markdown data dictionary to ``out_path``.

    The ``model_json_str`` parameter is expected to contain a JSON object with an
    ``entities`` array. Each entity should provide a ``name``, optional
    ``description`` and a list of ``attributes`` describing its fields. Attribute
    entries may include metadata such as ``type``, ``required``, ``primary_key``
    and ``unique``. Booleans are rendered as ``Yes``/``No`` in the markdown
    tables. Missing values are displayed as an em dash (``—``).
    """

    payload = _load_payload(model_json_str)
    entities = _normalise_entities(payload.get("entities", []))

    lines: list[str] = []
    lines.extend(_render_entities_section(entities))
    for entity in entities:
        lines.extend(_render_entity_table(entity))
    lines.extend(_render_dictionary_section(entities))

    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8")
    return destination


def _load_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError("Model payload must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Model payload must be a JSON object")

    model_block = payload.get("model")
    if isinstance(model_block, dict):
        return model_block
    return payload


def _normalise_entities(raw_entities: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_entities, list):
        return []

    entities: list[dict[str, Any]] = []
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = _coerce_str(item.get("name")) or "Unnamed Entity"
        description = _coerce_str(
            item.get("description")
            or item.get("summary")
            or item.get("details")
        )
        attributes = _normalise_attributes(item.get("attributes"))
        entities.append({
            "name": name,
            "description": description,
            "attributes": attributes,
        })

    entities.sort(key=lambda entry: entry["name"].lower())
    return entities


def _normalise_attributes(raw_attributes: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_attributes, list):
        return []

    attributes: list[dict[str, Any]] = []
    for item in raw_attributes:
        if not isinstance(item, dict):
            continue
        name = _coerce_str(item.get("name")) or "Unnamed Attribute"
        description = _coerce_str(
            item.get("description")
            or item.get("details")
            or item.get("summary")
        )
        data_type = _resolve_type(item)
        required = _resolve_required(item)
        primary_key = _resolve_flag(item, ("primary_key", "is_primary_key", "pk"))
        unique = _resolve_flag(item, ("unique", "is_unique"))

        attributes.append(
            {
                "name": name,
                "description": description,
                "type": data_type,
                "required": required,
                "primary_key": primary_key,
                "unique": unique,
            }
        )

    attributes.sort(key=lambda entry: entry["name"].lower())
    return attributes


def _render_entities_section(entities: list[dict[str, Any]]) -> list[str]:
    lines = ["# Entities\n\n", "| Entity | Description |\n", "| --- | --- |\n"]
    for entity in entities:
        lines.append(
            f"| {entity['name']} | {entity['description'] or '—'} |\n"
        )
    lines.append("\n")
    return lines


def _render_entity_table(entity: dict[str, Any]) -> list[str]:
    lines = [f"## {entity['name']}\n\n"]
    if entity["description"]:
        lines.append(f"{entity['description']}\n\n")
    lines.extend(
        [
            "| Attribute | Type | Required | Primary Key | Unique | Description |\n",
            "| --- | --- | --- | --- | --- | --- |\n",
        ]
    )
    for attribute in entity["attributes"]:
        lines.append(
            "| {name} | {type} | {required} | {primary_key} | {unique} | {description} |\n".format(
                name=attribute["name"],
                type=attribute["type"] or "—",
                required=_format_bool(attribute["required"]),
                primary_key=_format_bool(attribute["primary_key"]),
                unique=_format_bool(attribute["unique"]),
                description=attribute["description"] or "—",
            )
        )
    if not entity["attributes"]:
        lines.append("| — | — | — | — | — | — |\n")
    lines.append("\n")
    return lines


def _render_dictionary_section(entities: list[dict[str, Any]]) -> list[str]:
    lines = ["# Dictionary\n\n"]
    lines.extend(
        [
            "| Entity | Attribute | Type | Required | Primary Key | Unique | Description |\n",
            "| --- | --- | --- | --- | --- | --- | --- |\n",
        ]
    )
    for entity in entities:
        for attribute in entity["attributes"]:
            lines.append(
                "| {entity} | {name} | {type} | {required} | {primary_key} | {unique} | {description} |\n".format(
                    entity=entity["name"],
                    name=attribute["name"],
                    type=attribute["type"] or "—",
                    required=_format_bool(attribute["required"]),
                    primary_key=_format_bool(attribute["primary_key"]),
                    unique=_format_bool(attribute["unique"]),
                    description=attribute["description"] or "—",
                )
            )
        if not entity["attributes"]:
            lines.append(
                f"| {entity['name']} | — | — | — | — | — | — |\n"
            )
    lines.append("\n")
    return lines


def _resolve_type(attribute: dict[str, Any]) -> str:
    for key in ("type", "data_type", "dataType", "field_type", "attribute_type"):
        value = attribute.get(key)
        if value:
            return _coerce_str(value)
    return "—"


def _resolve_required(attribute: dict[str, Any]) -> bool | None:
    explicit = _resolve_flag(attribute, ("required",))
    if explicit is not None:
        return explicit
    nullable = _resolve_flag(attribute, ("nullable",))
    if nullable is None:
        return None
    return not nullable


def _resolve_flag(attribute: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        if key not in attribute:
            continue
        value = attribute[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower = value.strip().lower()
            if lower in _BOOL_TRUE:
                return True
            if lower in _BOOL_FALSE:
                return False
        if isinstance(value, (int, float)):
            if value in (0, 1):
                return bool(value)
    return None


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "—"
    return "Yes" if value else "No"

