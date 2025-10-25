"""PlantUML diagram exporter."""

from __future__ import annotations

from pathlib import Path

from slugify import slugify

from src.models.tables import Domain, Entity


def _class_name(entity: Entity) -> str:
    token = slugify(entity.name, separator="_")
    return token or f"entity_{entity.id}"


def export_plantuml(domain: Domain, output_dir: Path) -> Path:
    """Generate a PlantUML class diagram for ``domain``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{slugify(domain.name)}.puml"

    lines: list[str] = [
        "@startuml",
        "skinparam classAttributeIconSize 0",
        f"title {domain.name}",
    ]

    entities = sorted(domain.entities, key=lambda item: item.name.lower())
    for entity in entities:
        class_name = _class_name(entity)
        lines.append(f"class {class_name} {{")
        if entity.description:
            for description_line in entity.description.splitlines():
                lines.append(f"  ' {description_line}")
        for attribute in sorted(entity.attributes, key=lambda item: item.name.lower()):
            data_type = attribute.data_type or "unspecified"
            nullable = "?" if attribute.is_nullable else "!"
            lines.append(f"  {attribute.name}: {data_type} {nullable}")
        lines.append("}")

    relationships = sorted(
        domain.relationships,
        key=lambda rel: (rel.from_entity.name.lower(), rel.to_entity.name.lower(), rel.relationship_type),
    )
    for relationship in relationships:
        left = _class_name(relationship.from_entity)
        right = _class_name(relationship.to_entity)
        label = relationship.relationship_type or "relates to"
        lines.append(f"{left} --> {right} : {label}")
        if relationship.description:
            for description_line in relationship.description.splitlines():
                lines.append(f"' {description_line}")

    lines.append("@enduml")
    file_path.write_text("\n".join(lines), encoding="utf-8")
    return file_path


__all__ = ["export_plantuml"]

