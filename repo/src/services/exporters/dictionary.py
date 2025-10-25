"""Export a data dictionary for a model."""
from __future__ import annotations

from pathlib import Path

from slugify import slugify

from src.models.tables import DataModel


def export_dictionary(model: DataModel, output_dir: Path) -> Path:
    """Write a markdown data dictionary for the model."""

    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{slugify(model.name)}-dictionary.md"
    content = [
        f"# {model.name} Data Dictionary\n",
        f"Generated from domain: {model.domain.name}\n\n",
        f"## Summary\n{model.summary}\n\n",
        "## Definition\n",
        model.definition.strip(),
        "\n",
    ]
    file_path.write_text("".join(content), encoding="utf-8")
    return file_path
