"""Create PlantUML diagrams from model definitions."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from slugify import slugify

from src.services.exporters.utils import prepare_artifact_path


def emit_plantuml(model: Mapping[str, Any], artifacts_dir: Path) -> Path:
    """Generate a PlantUML class diagram stub from a model payload."""

    name = _extract_name(model)
    domain_name = _extract_domain_name(model)
    definition = str(model.get("definition") or "").strip()

    filename = f"{_slug(name)}.puml"
    file_path = prepare_artifact_path(artifacts_dir, filename)

    definition_lines = [
        f"' {line}" for line in definition.splitlines() if line.strip()
    ]
    content = "\n".join(
        [
            "@startuml",
            "skinparam classAttributeIconSize 0",
            f"title {name}{f' ({domain_name})' if domain_name else ''}",
            "' Model definition excerpt:",
            *definition_lines,
            "@enduml",
        ]
    )
    file_path.write_text(content, encoding="utf-8")
    return file_path


def export_plantuml(model: "DataModel", output_dir: Path) -> Path:  # pragma: no cover - legacy shim
    """Backward compatible wrapper for existing callers expecting ORM models."""

    payload = {
        "name": model.name,
        "definition": model.definition,
        "domain": {"name": model.domain.name if model.domain else None},
    }
    return emit_plantuml(payload, output_dir)


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
