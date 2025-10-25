"""Export a data dictionary for a model."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from slugify import slugify

from src.models.tables import Domain, Entity


def _render_entity(entity: Entity) -> list[str]:
    """Render an entity section for the data dictionary."""

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
    """Write a markdown data dictionary for a domain."""

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


def export_dictionary(model: "DataModel", output_dir: Path) -> Path:  # pragma: no cover - legacy shim
    """Backward compatible wrapper for existing callers expecting ORM models."""

    payload = {
        "name": model.name,
        "summary": model.summary,
        "definition": model.definition,
        "domain": {"name": model.domain.name if model.domain else None},
    }
    return emit_dictionary_md(payload, output_dir)


def _extract_name(model: Mapping[str, Any]) -> str:
    value = str(model.get("name") or "Model").strip()
    return value or "Model"


def _extract_domain_name(model: Mapping[str, Any]) -> str:
    domain = model.get("domain")
    if isinstance(domain, Mapping):
        raw = domain.get("name")
    else:
        raw = model.get("domain_name")
    return str(raw).strip() if raw else ""


def _slug(value: str) -> str:
    slug = slugify(value)
    return slug or "model"


from src.models.tables import DataModel  # noqa: E402  # isort:skip
