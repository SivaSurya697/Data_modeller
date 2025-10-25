"""Determine the impact of generated models."""
from __future__ import annotations

from difflib import unified_diff
from typing import Iterable, Sequence

from src.models.tables import Entity


def _entity_snapshot(entity: Entity) -> list[str]:
    """Create a deterministic textual snapshot for diffing."""

    lines = [
        f"Entity: {entity.name}",
        f"Description: {(entity.description or '').strip()}",
        f"Documentation: {(entity.documentation or '').strip()}",
    ]
    attribute_lines = [
        f"- {attribute.name}::{attribute.data_type or 'unspecified'}::{attribute.description or ''}::{int(attribute.is_nullable)}"
        for attribute in sorted(entity.attributes, key=lambda attr: attr.name.lower())
    ]
    if attribute_lines:
        lines.append("Attributes:")
        lines.extend(attribute_lines)
    return lines


def evaluate_model_impact(
    existing_entities: Sequence[Entity],
    new_entities: Sequence[Entity],
    change_hints: Iterable[str] | None = None,
) -> list[str]:
    """Generate a human readable impact assessment between entity sets."""

    impact: list[str] = []
    if change_hints:
        impact.extend([hint.strip() for hint in change_hints if hint.strip()])

    if not existing_entities:
        impact.append("No prior entities exist for comparison.")
        return impact

    existing_names = {entity.name: entity for entity in existing_entities}
    new_names = {entity.name: entity for entity in new_entities}

    added = sorted(set(new_names) - set(existing_names))
    removed = sorted(set(existing_names) - set(new_names))

    if added:
        impact.append("New entities detected: " + ", ".join(added))
    if removed:
        impact.append("Entities removed: " + ", ".join(removed))

    shared_names = sorted(set(existing_names) & set(new_names))
    for name in shared_names:
        previous = _entity_snapshot(existing_names[name])
        current = _entity_snapshot(new_names[name])
        diff = list(
            unified_diff(
                previous,
                current,
                fromfile=f"previous:{name}",
                tofile=f"candidate:{name}",
                lineterm="",
            )
        )
        if diff:
            impact.append(f"Changes detected for entity '{name}':")
            impact.extend(diff[:50])

    if not impact:
        impact.append("No structural differences detected against the latest entities.")

    return impact
