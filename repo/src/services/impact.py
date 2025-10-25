"""Determine the downstream impact of shared dimension changes."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_VALID_IMPACT_LEVELS = {"low", "medium", "high"}


def _normalise_consumers(value: Any) -> list[str]:
    """Flatten consumer containers into an ordered list of unique strings."""

    if value is None:
        return []

    normalised: list[str] = []

    def _walk(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, str):
            candidate = item.strip()
            if candidate:
                normalised.append(candidate)
            return
        if isinstance(item, Mapping):
            for key, nested in item.items():
                # Treat truthy scalar values as a signal that the key is a consumer name.
                if isinstance(nested, (bool, int, float)):
                    if nested:
                        candidate = str(key).strip()
                        if candidate:
                            normalised.append(candidate)
                else:
                    _walk(nested)
            return
        if isinstance(item, Iterable):
            for nested in item:
                _walk(nested)
            return
        candidate = str(item).strip()
        if candidate:
            normalised.append(candidate)

    _walk(value)

    seen: set[str] = set()
    unique: list[str] = []
    for consumer in normalised:
        if consumer not in seen:
            seen.add(consumer)
            unique.append(consumer)
    return unique


def _resolve_impact_level(change: Mapping[str, Any]) -> str:
    """Infer the impact level for a change using heuristics and hints."""

    raw_level = change.get("impact_level")
    if isinstance(raw_level, str):
        candidate = raw_level.strip().lower()
        if candidate in _VALID_IMPACT_LEVELS:
            return candidate

    if change.get("breaking"):
        return "high"

    text_fragments = [
        change.get("change_type"),
        change.get("action"),
        change.get("summary"),
        change.get("description"),
        change.get("details"),
        change.get("explanation"),
    ]
    combined = " ".join(
        fragment.strip() if isinstance(fragment, str) else str(fragment)
        for fragment in text_fragments
        if fragment
    ).lower()

    if any(keyword in combined for keyword in ("remove", "drop", "delete", "retire", "rename")):
        return "high"
    if any(keyword in combined for keyword in ("modify", "change", "replace", "update", "revise")):
        return "medium"
    if any(keyword in combined for keyword in ("add", "introduce", "new", "extend", "augment")):
        return "low"

    # Fall back to medium to highlight the change without overstating urgency.
    return "medium"


def _compose_explanation(change: Mapping[str, Any], dimension: str) -> str:
    """Build a human readable explanation from the change payload."""

    for key in ("explanation", "summary", "description", "details", "reason", "change"):
        value = change.get(key)
        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                return candidate

    attribute = None
    for key in ("attribute", "field", "column", "member"):
        raw = change.get(key)
        if isinstance(raw, str) and raw.strip():
            attribute = raw.strip()
            break

    action = None
    for key in ("change_type", "action", "operation"):
        raw = change.get(key)
        if isinstance(raw, str) and raw.strip():
            action = raw.strip()
            break

    if attribute and action:
        return f"{attribute}: {action}."
    if action:
        return f"{action} within the {dimension} dimension."
    if attribute:
        return f"Update related to {attribute} in the {dimension} dimension."

    return f"Review updates to the {dimension} dimension."


def compute_impact(
    shared_dim_changes: Iterable[Mapping[str, Any]] | None,
    consumers_index: Mapping[str, Sequence[str] | Iterable[str]] | None,
) -> list[dict[str, str]]:
    """Expand shared dimension changes into per-consumer impact entries."""

    impact: list[dict[str, str]] = []
    if not shared_dim_changes:
        return impact

    consumer_lookup = {
        str(dimension).strip(): _normalise_consumers(consumers)
        for dimension, consumers in (consumers_index or {}).items()
        if str(dimension).strip()
    }

    seen: set[tuple[str, str, str]] = set()

    for change in shared_dim_changes:
        if not isinstance(change, Mapping):
            continue

        dimension_raw = (
            change.get("dimension")
            or change.get("shared_dimension")
            or change.get("name")
        )
        dimension = str(dimension_raw).strip() if dimension_raw is not None else ""
        if not dimension:
            continue

        consumer_candidates = _normalise_consumers(
            change.get("consumers")
            or change.get("consumer")
            or change.get("downstream")
            or change.get("impacted_consumers")
        )
        mapped_consumers = consumer_lookup.get(dimension, [])
        if consumer_candidates:
            consumers = [
                consumer
                for consumer in mapped_consumers
                if consumer in consumer_candidates
            ] or consumer_candidates
        else:
            consumers = mapped_consumers

        if not consumers:
            consumers = ["Unmapped downstream"]

        impact_level = _resolve_impact_level(change)
        explanation = _compose_explanation(change, dimension)

        for consumer in consumers:
            record_key = (dimension, consumer, explanation)
            if record_key in seen:
                continue
            seen.add(record_key)
            impact.append(
                {
                    "dimension": dimension,
                    "consumer": consumer,
                    "impact_level": impact_level,
                    "explanation": explanation,
                }
            )

    return impact

