"""Determine the impact of generated models."""
from __future__ import annotations

from difflib import unified_diff
from typing import Iterable, Sequence

from src.models.tables import DataModel


def evaluate_model_impact(
    existing_models: Sequence[DataModel],
    new_definition: str,
    change_hints: Iterable[str] | None = None,
) -> list[str]:
    """Generate a human readable impact assessment."""

    impact: list[str] = []
    if change_hints:
        impact.extend([hint.strip() for hint in change_hints if hint.strip()])

    if existing_models:
        previous_definition = existing_models[0].definition
        diff = list(
            unified_diff(
                previous_definition.splitlines(),
                new_definition.splitlines(),
                fromfile="previous",
                tofile="candidate",
                lineterm="",
            )
        )
        if diff:
            impact.append("Detected definition differences:")
            impact.extend(diff[:50])  # guard against overly long output
        else:
            impact.append("No structural differences detected against the latest model.")
    else:
        impact.append("No prior models exist for comparison.")

    return impact
