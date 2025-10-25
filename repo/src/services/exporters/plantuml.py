"""Create PlantUML diagrams from model definitions."""
from __future__ import annotations

from pathlib import Path

from slugify import slugify

from src.models.tables import DataModel


def export_plantuml(model: DataModel, output_dir: Path) -> Path:
    """Generate a PlantUML class diagram stub."""

    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{slugify(model.name)}.puml"
    definition_lines = "\n".join(
        f"' {line}" for line in model.definition.strip().splitlines()
    )
    content = "\n".join(
        [
            "@startuml",
            "skinparam classAttributeIconSize 0",
            f"title {model.name} ({model.domain.name})",
            "' Model definition excerpt:",
            definition_lines,
            "@enduml",
        ]
    )
    file_path.write_text(content, encoding="utf-8")
    return file_path
