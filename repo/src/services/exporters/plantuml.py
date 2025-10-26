"""PlantUML diagram exporter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slugify import slugify

from src.models.tables import Domain, Entity
from src.services.model_analysis import (
    classify_entity,
    extract_relationship_cardinality,
    infer_model_version,
)
from src.services.exporters.utils import prepare_artifact_path


def _class_name(entity: Entity) -> str:
    token = slugify(entity.name, separator="_")
    return token or f"entity_{entity.id}"


def _render_entity_block(entity: Entity, classification: str) -> list[str]:
    class_name = _class_name(entity)
    stereotype = None
    if classification == "fact":
        stereotype = "Fact"
    elif classification == "dimension":
        stereotype = "Dimension"

    header = f"class {class_name}"
    if stereotype:
        header += f" <<{stereotype}>>"

    block = [header + " {"]
    if entity.description:
        for description_line in entity.description.splitlines():
            block.append(f"  ' {description_line}")
    for attribute in sorted(entity.attributes, key=lambda item: item.name.lower()):
        data_type = attribute.data_type or "unspecified"
        nullable = "?" if attribute.is_nullable else "!"
        block.append(f"  {attribute.name}: {data_type} {nullable}")
    block.append("}")
    return block


def export_plantuml(domain: Domain, output_dir: Path) -> Path:
    """Generate a PlantUML class diagram for ``domain``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{slugify(domain.name)}.puml"

    models = list(domain.models)
    versions = [model.version for model in models if getattr(model, "version", None) is not None]
    if versions:
        latest_version = max(versions)
    elif models:
        latest_version = infer_model_version(domain)
    else:
        latest_version = None
    title = domain.name if latest_version is None else f"{domain.name} (v{latest_version})"

    lines: list[str] = [
        "@startuml",
        "skinparam classAttributeIconSize 0",
        f"title {title}",
    ]

    grouped_entities: dict[str, list[list[str]]] = {"fact": [], "dimension": [], "other": []}

    entities = sorted(domain.entities, key=lambda item: item.name.lower())
    for entity in entities:
        classification = classify_entity(entity)
        block = _render_entity_block(entity, classification)
        grouped_entities.get(classification, grouped_entities["other"]).append(block)

    if grouped_entities["fact"]:
        lines.append('package "Facts" {')
        for block in grouped_entities["fact"]:
            lines.extend(f"  {line}" if line else "" for line in block)
        lines.append("}")
    if grouped_entities["dimension"]:
        lines.append('package "Dimensions" {')
        for block in grouped_entities["dimension"]:
            lines.extend(f"  {line}" if line else "" for line in block)
        lines.append("}")
    for block in grouped_entities["other"]:
        lines.extend(block)

    relationships = sorted(
        domain.relationships,
        key=lambda rel: (
            rel.from_entity.name.lower(),
            rel.to_entity.name.lower(),
            rel.relationship_type or "",
        ),
    )
    for relationship in relationships:
        left = _class_name(relationship.from_entity)
        right = _class_name(relationship.to_entity)
        label = (relationship.relationship_type or "relates to").strip()
        left_cardinality, right_cardinality = extract_relationship_cardinality(relationship)

        relationship_line = left
        if left_cardinality:
            relationship_line += f' "{left_cardinality}"'
        relationship_line += " -->"
        if right_cardinality:
            relationship_line += f' "{right_cardinality}" {right}'
        else:
            relationship_line += f" {right}"
        if label:
            relationship_line += f" : {label}"
        lines.append(relationship_line)

        if relationship.description:
            for description_line in relationship.description.splitlines():
                lines.append(f"' {description_line}")

    lines.append("@enduml")
    file_path.write_text("\n".join(lines), encoding="utf-8")
    return file_path


__all__ = ["export_plantuml"]


def _normalise_entities(model_payload: dict[str, Any]) -> list[dict[str, Any]]:
    entities = model_payload.get("entities")
    if not isinstance(entities, list):
        return []
    normalised: list[dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        role = str(entity.get("role") or "").strip().lower()
        attributes = entity.get("attributes")
        if not isinstance(attributes, list):
            attributes = []
        normalised.append(
            {
                "name": name,
                "role": role,
                "description": str(entity.get("description") or "").strip(),
                "attributes": [
                    {
                        "name": str(attribute.get("name") or "").strip(),
                        "data_type": str(attribute.get("data_type") or "").strip(),
                        "is_nullable": bool(attribute.get("is_nullable", True)),
                    }
                    for attribute in attributes
                    if isinstance(attribute, dict)
                ],
            }
        )
    return normalised


def _normalise_relationships(model_payload: dict[str, Any]) -> list[dict[str, Any]]:
    relationships = model_payload.get("relationships")
    if not isinstance(relationships, list):
        return []
    result: list[dict[str, Any]] = []
    for relationship in relationships:
        if not isinstance(relationship, dict):
            continue
        result.append(
            {
                "from": str(
                    relationship.get("from")
                    or relationship.get("source")
                    or relationship.get("from_entity")
                    or ""
                ).strip(),
                "to": str(
                    relationship.get("to")
                    or relationship.get("target")
                    or relationship.get("to_entity")
                    or ""
                ).strip(),
                "type": str(relationship.get("type") or "").strip(),
                "description": str(relationship.get("description") or "").strip(),
            }
        )
    return result


def emit_plantuml(model_json_str: str, out_path: str) -> None:
    """Write a PlantUML diagram based on ``model_json_str``."""

    try:
        payload = json.loads(model_json_str)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError("Invalid model JSON") from exc

    entities = _normalise_entities(payload)
    relationships = _normalise_relationships(payload)

    title = str(payload.get("name") or payload.get("domain") or "Model Diagram").strip()
    if not title:
        title = "Model Diagram"

    output_path = prepare_artifact_path(Path(out_path).parent, Path(out_path).name)

    lines: list[str] = [
        "@startuml",
        "skinparam classAttributeIconSize 0",
        f"title {title}",
    ]

    for entity in entities:
        stereotype = None
        if entity["role"] == "fact":
            stereotype = "Fact"
        elif entity["role"] == "dimension":
            stereotype = "Dimension"

        header = f"class {entity['name']}"
        if stereotype:
            header += f" <<{stereotype}>>"
        lines.append(header + " {")
        if entity["description"]:
            for description_line in entity["description"].splitlines():
                lines.append(f"  ' {description_line}")
        for attribute in entity["attributes"]:
            nullable = "?" if attribute["is_nullable"] else "!"
            lines.append(
                f"  {attribute['name']}: {attribute['data_type'] or 'unspecified'} {nullable}"
            )
        lines.append("}")

    for relationship in relationships:
        if not (relationship["from"] and relationship["to"]):
            continue
        relation_line = f"{relationship['from']} --> {relationship['to']}"
        if relationship["type"]:
            relation_line += f" : {relationship['type']}"
        lines.append(relation_line)
        if relationship["description"]:
            for description_line in relationship["description"].splitlines():
                lines.append(f"' {description_line}")

    lines.append("@enduml")
    output_path.write_text("\n".join(lines), encoding="utf-8")


__all__.append("emit_plantuml")
