"""Export a data dictionary for a model."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from slugify import slugify

from src.services.exporters.utils import prepare_artifact_path


def emit_dictionary_md(model: Mapping[str, Any], artifacts_dir: Path) -> Path:
    """Write a markdown data dictionary for the provided model payload."""

    name = _extract_name(model)
    domain_name = _extract_domain_name(model)
    summary = str(model.get("summary") or "").strip()
    definition = str(model.get("definition") or "").strip()

    filename = f"{_slug(name)}-dictionary.md"
    file_path = prepare_artifact_path(artifacts_dir, filename)

    sections = [f"# {name} Data Dictionary\n"]
    if domain_name:
        sections.append(f"Generated from domain: {domain_name}\n\n")
    if summary:
        sections.append(f"## Summary\n{summary}\n\n")
    if definition:
        sections.extend(["## Definition\n", definition, "\n"])

    file_path.write_text("".join(sections), encoding="utf-8")
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
