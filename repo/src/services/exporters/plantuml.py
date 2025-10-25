"""Emit PlantUML diagrams from JSON model definitions."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_CARDINALITY_SYMBOLS: dict[str, str] = {
    "zero_or_one": "o|",
    "one": "||",
    "zero_or_many": "o{",
    "many": "{",
}


def _normalise_identifier(label: str, used: set[str]) -> str:
    """Create a PlantUML-safe identifier from a human readable label."""

    base = re.sub(r"\W+", "_", label).strip("_") or "Entity"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _attribute_line(attribute: dict[str, Any]) -> str:
    """Render a single attribute row inside an entity block."""

    name = attribute.get("name", "attribute")
    data_type = attribute.get("type")
    description = attribute.get("description")
    is_primary = bool(attribute.get("is_primary_key"))
    is_nullable = attribute.get("is_nullable")

    prefix = "*" if is_primary else ""
    line = f"  {prefix}{name}"
    if data_type:
        line += f" : {data_type}"
    if is_nullable is False and not is_primary:
        line += " {not null}"
    if description:
        line += f" // {description}"
    return line


def _relationship_line(
    relation: dict[str, Any],
    aliases: dict[str, str],
) -> str | None:
    """Render a PlantUML relationship statement if possible."""

    raw_from = (
        relation.get("from_entity")
        or relation.get("from")
        or relation.get("source")
        or relation.get("left")
    )
    raw_to = (
        relation.get("to_entity")
        or relation.get("to")
        or relation.get("target")
        or relation.get("right")
    )
    if not raw_from or not raw_to:
        return None

    cardinality = relation.get("cardinality") or {}
    from_cardinality = (
        relation.get("from_cardinality")
        or relation.get("source_cardinality")
        or cardinality.get("from")
        or cardinality.get("source")
    )
    to_cardinality = (
        relation.get("to_cardinality")
        or relation.get("target_cardinality")
        or cardinality.get("to")
        or cardinality.get("target")
    )

    left_symbol = _CARDINALITY_SYMBOLS.get(from_cardinality, "")
    right_symbol = _CARDINALITY_SYMBOLS.get(to_cardinality, "")
    connector = f"{left_symbol}--{right_symbol}" if (left_symbol or right_symbol) else "--"

    label = relation.get("name") or relation.get("label") or relation.get("description")
    lhs = aliases.get(str(raw_from), str(raw_from))
    rhs = aliases.get(str(raw_to), str(raw_to))
    if label:
        return f"{lhs} {connector} {rhs} : {label}"
    return f"{lhs} {connector} {rhs}"


def emit_plantuml(model_json_str: str, out_path: str) -> None:
    """Emit a PlantUML entity-relationship diagram to ``out_path``.

    Parameters
    ----------
    model_json_str:
        JSON string describing the data model. The payload is expected to contain
        ``entities`` and optional ``relationships`` collections.
    out_path:
        Destination file path for the generated PlantUML diagram.
    """

    try:
        model = json.loads(model_json_str)
    except json.JSONDecodeError as exc:  # pragma: no cover - error propagation
        raise ValueError("model_json_str must be valid JSON") from exc

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = ["@startuml"]

    title = model.get("name")
    domain = model.get("domain", {}) if isinstance(model.get("domain"), dict) else None
    domain_name = domain.get("name") if isinstance(domain, dict) else None
    if isinstance(title, str):
        if isinstance(domain_name, str):
            lines.append(f"title {title} ({domain_name})")
        else:
            lines.append(f"title {title}")

    entities = model.get("entities") if isinstance(model, dict) else None
    aliases: dict[str, str] = {}
    used_aliases: set[str] = set()

    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_name = str(entity.get("name") or "Entity")
            alias = _normalise_identifier(entity_name, used_aliases)
            aliases[entity_name] = alias
            aliases[alias] = alias

            lines.append("")
            lines.append(f'entity "{entity_name}" as {alias} {{')

            attributes = entity.get("attributes")
            if isinstance(attributes, list) and attributes:
                for attribute in attributes:
                    if isinstance(attribute, dict):
                        lines.append(_attribute_line(attribute))
            lines.append("}")

    relationships = model.get("relationships") if isinstance(model, dict) else None
    if isinstance(relationships, list):
        for relation in relationships:
            if not isinstance(relation, dict):
                continue
            statement = _relationship_line(relation, aliases)
            if statement:
                lines.append("")
                lines.append(statement)

    lines.append("@enduml")
    path.write_text("\n".join(lines), encoding="utf-8")

