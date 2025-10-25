"""Utility helpers to compare entity snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from typing import Iterable, Sequence

from src.models.tables import Entity


@dataclass(slots=True)
class ImpactItem:
    """Structured description of an impact observation."""

    dimension: str
    consumer: str
    impact_level: str
    explanation: str


def _entity_snapshot(entity: Entity) -> list[str]:
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
) -> list[ImpactItem]:
    """Return a list of impact observations between two entity sets."""

    impact: list[ImpactItem] = []

    if change_hints:
        for hint in change_hints:
            explanation = hint.strip()
            if explanation:
                impact.append(
                    ImpactItem(
                        dimension="model",
                        consumer="reviewer",
                        impact_level="medium",
                        explanation=explanation,
                    )
                )

    if not existing_entities:
        impact.append(
            ImpactItem(
                dimension="model",
                consumer="all",
                impact_level="low",
                explanation="No prior entities exist for comparison.",
            )
        )
        return impact

    existing_map = {entity.name: entity for entity in existing_entities}
    new_map = {entity.name: entity for entity in new_entities}

    added = sorted(set(new_map) - set(existing_map))
    removed = sorted(set(existing_map) - set(new_map))

    if added:
        impact.append(
            ImpactItem(
                dimension="entities",
                consumer="analysts",
                impact_level="medium",
                explanation="New entities detected: " + ", ".join(added),
            )
        )
    if removed:
        impact.append(
            ImpactItem(
                dimension="entities",
                consumer="analysts",
                impact_level="high",
                explanation="Entities removed: " + ", ".join(removed),
            )
        )

    shared_names = sorted(set(existing_map) & set(new_map))
    for name in shared_names:
        previous = _entity_snapshot(existing_map[name])
        current = _entity_snapshot(new_map[name])
        diff_lines = list(
            unified_diff(
                previous,
                current,
                fromfile=f"previous:{name}",
                tofile=f"candidate:{name}",
                lineterm="",
            )
        )
        if diff_lines:
            explanation = "\n".join(diff_lines[:50])
            impact.append(
                ImpactItem(
                    dimension="entities",
                    consumer="reviewer",
                    impact_level="medium",
                    explanation=f"Changes detected for entity '{name}':\n{explanation}",
                )
            )

    if not impact:
        impact.append(
            ImpactItem(
                dimension="model",
                consumer="all",
                impact_level="low",
                explanation="No structural differences detected against the latest entities.",
            )
        )

    return impact


__all__ = ["ImpactItem", "evaluate_model_impact"]

