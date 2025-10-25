"""PlantUML diagram exporter."""

from __future__ import annotations

from pathlib import Path

from slugify import slugify

from src.models.tables import Domain, Entity
from src.services.model_analysis import (
    classify_entity,
    extract_relationship_cardinality,
    infer_model_version,
)


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

    version = infer_model_version(domain)

    lines: list[str] = [
        "@startuml",
        "skinparam classAttributeIconSize 0",
        "skinparam class {",
        "  BackgroundColor<<Fact>> #FFF2CC",
        "  BackgroundColor<<Dimension>> #D9E8FB",
        "  BorderColor<<Fact>> #A56800",
        "  BorderColor<<Dimension>> #2B579A",
        "}",
        f"title {domain.name} (v{version})",
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
