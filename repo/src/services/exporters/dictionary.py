"""Markdown dictionary exporter."""

from __future__ import annotations

from pathlib import Path

from slugify import slugify

from src.models.tables import Domain, Entity


def _render_entity(entity: Entity) -> list[str]:
    lines = [f"### {entity.name}\n"]
    if entity.description:
        lines.append(f"{entity.description}\n\n")
    if entity.documentation:
        lines.append(f"{entity.documentation}\n\n")
    if entity.attributes:
        lines.append("| Attribute | Type | Nullable | Description |\n")
        lines.append("| --- | --- | --- | --- |\n")
        for attribute in sorted(entity.attributes, key=lambda item: item.name.lower()):
            data_type = attribute.data_type or "unspecified"
            nullable = "Yes" if attribute.is_nullable else "No"
            description = attribute.description or ""
            lines.append(
                f"| {attribute.name} | {data_type} | {nullable} | {description} |\n"
            )
        lines.append("\n")
    return lines


def export_dictionary(domain: Domain, output_dir: Path) -> Path:
    """Write a markdown data dictionary for ``domain``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{slugify(domain.name)}-dictionary.md"
    content: list[str] = [
        f"# {domain.name} Data Dictionary\n",
        f"Domain description: {domain.description}\n\n",
    ]
    entities = sorted(domain.entities, key=lambda item: item.name.lower())
    if entities:
        content.append("## Entities\n\n")
        for entity in entities:
            content.extend(_render_entity(entity))
    else:
        content.append("No entities defined for this domain yet.\n")

    file_path.write_text("".join(content), encoding="utf-8")
    return file_path


__all__ = ["export_dictionary"]

