"""Markdown dictionary exporter."""

from __future__ import annotations

import json
from typing import Any

from pathlib import Path

from slugify import slugify

from src.models.tables import Domain, Entity
from src.services.exporters.utils import prepare_artifact_path


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
    latest_version = max((model.version for model in domain.models), default=None)
    content: list[str] = [
        f"# {domain.name} Data Dictionary\n",
        f"Domain description: {domain.description}\n\n",
    ]
    if latest_version is not None:
        content.append(f"Latest model version: v{latest_version}\n\n")
    else:
        content.append("Latest model version: unavailable\n\n")
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


def _normalise_entity(entity: dict[str, Any]) -> dict[str, Any]:
    name = str(entity.get("name") or "").strip()
    description = str(entity.get("description") or "").strip()
    documentation = str(entity.get("documentation") or "").strip()
    attributes = entity.get("attributes")
    if not isinstance(attributes, list):
        attributes = []
    normalised_attributes: list[dict[str, Any]] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        normalised_attributes.append(
            {
                "name": str(attribute.get("name") or "").strip(),
                "data_type": str(attribute.get("data_type") or "").strip(),
                "description": str(attribute.get("description") or "").strip(),
                "is_nullable": bool(attribute.get("is_nullable", True)),
            }
        )
    return {
        "name": name,
        "description": description,
        "documentation": documentation,
        "attributes": normalised_attributes,
    }


def emit_dictionary_md(model_json_str: str, out_path: str) -> None:
    """Write a markdown dictionary derived from ``model_json_str``."""

    try:
        payload = json.loads(model_json_str)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError("Invalid model JSON") from exc

    entities = payload.get("entities")
    if not isinstance(entities, list):
        entities = []

    output_path = prepare_artifact_path(Path(out_path).parent, Path(out_path).name)

    lines: list[str] = ["# Data Dictionary\n\n"]
    if not entities:
        lines.append("No entities defined.\n")
    else:
        for entity in entities:
            normalised = _normalise_entity(entity)
            if not normalised["name"]:
                continue
            lines.append(f"## {normalised['name']}\n\n")
            if normalised["description"]:
                lines.append(f"{normalised['description']}\n\n")
            if normalised["documentation"]:
                lines.append(f"{normalised['documentation']}\n\n")
            if normalised["attributes"]:
                lines.append("| Attribute | Type | Nullable | Description |\n")
                lines.append("| --- | --- | --- | --- |\n")
                for attribute in normalised["attributes"]:
                    nullable = "Yes" if attribute["is_nullable"] else "No"
                    lines.append(
                        f"| {attribute['name']} | {attribute['data_type']} | {nullable} | {attribute['description']} |\n"
                    )
                lines.append("\n")

    output_path.write_text("".join(lines), encoding="utf-8")


__all__.append("emit_dictionary_md")

