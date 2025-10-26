"""Utility helpers for extracting baseline objects from model JSON."""

from __future__ import annotations

import json
from typing import Any, Mapping


def _load_payload(model_json: str) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(model_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def extract_entity_by_name(baseline_model_json: str, name: str) -> dict[str, Any] | None:
    """Return an entity definition from ``baseline_model_json`` if present."""

    payload = _load_payload(baseline_model_json)
    if payload is None:
        return None

    entities = payload.get("entities")
    if not isinstance(entities, list):
        return None

    needle = name.strip().lower()
    for entity in entities:
        if not isinstance(entity, Mapping):
            continue
        entity_name = str(entity.get("name") or "").strip()
        if entity_name.lower() == needle:
            return dict(entity)
    return None


def extract_relationship_by_pair(
    baseline_model_json: str, from_name: str, to_name: str
) -> dict[str, Any] | None:
    """Return a relationship from ``baseline_model_json`` matching ``from`` → ``to``."""

    payload = _load_payload(baseline_model_json)
    if payload is None:
        return None

    relationships = payload.get("relationships")
    if not isinstance(relationships, list):
        return None

    lhs = from_name.strip().lower()
    rhs = to_name.strip().lower()

    for relationship in relationships:
        if not isinstance(relationship, Mapping):
            continue
        source = str(
            relationship.get("from")
            or relationship.get("source")
            or relationship.get("from_entity")
            or relationship.get("from_name")
            or ""
        ).strip()
        target = str(
            relationship.get("to")
            or relationship.get("target")
            or relationship.get("to_entity")
            or relationship.get("to_name")
            or ""
        ).strip()
        if not source or not target:
            continue
        if source.lower() == lhs and target.lower() == rhs:
            return dict(relationship)
    return None


__all__ = ["extract_entity_by_name", "extract_relationship_by_pair"]

