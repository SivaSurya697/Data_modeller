"""MECE coverage analysis utilities for logical models."""

from __future__ import annotations

import json
from itertools import combinations
from typing import Dict, List, Tuple

from rapidfuzz import fuzz

from .ontology_pack import ONTOLOGY, canonical_entity_name, suggest_preferred_attr


def parse_model(model_json_str: str) -> dict:
    """Parse and validate the supplied model JSON string."""

    try:
        model = json.loads(model_json_str)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive branch
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc

    if not isinstance(model, dict):
        raise ValueError("Model JSON must decode to an object.")

    return model


def list_entity_attrs(model: dict) -> List[Tuple[str, str]]:
    """Return ``(entity_name, attribute_name)`` pairs from the model."""

    results: List[Tuple[str, str]] = []
    entities = model.get("entities", [])
    if not isinstance(entities, list):
        return results

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_name = str(entity.get("name") or "").strip()
        if not entity_name:
            continue
        attributes = entity.get("attributes", [])
        if isinstance(attributes, dict):
            attr_iterable = [
                str(name) for name in attributes.keys() if str(name).strip()
            ]
        else:
            attr_iterable = []
            for attribute in attributes:
                if isinstance(attribute, dict):
                    attr_name = str(attribute.get("name") or "").strip()
                else:
                    attr_name = str(attribute).strip()
                if attr_name:
                    attr_iterable.append(attr_name)
        for attr_name in attr_iterable:
            results.append((entity_name, attr_name))
    return results


def _normalise_name(value: str) -> str:
    return value.strip().lower()


def find_collisions(model: dict, threshold: float = 0.9) -> List[Dict]:
    """Detect attribute name collisions across distinct entities."""

    collisions: Dict[frozenset, Dict] = {}
    attrs = list_entity_attrs(model)
    if not attrs:
        return []

    for (entity_a, attr_a), (entity_b, attr_b) in combinations(attrs, 2):
        if entity_a == entity_b:
            continue
        score = fuzz.token_sort_ratio(attr_a, attr_b) / 100.0
        if score < threshold:
            continue
        key = frozenset({(entity_a, attr_a), (entity_b, attr_b)})
        if key not in collisions:
            representative = attr_a if len(attr_a) <= len(attr_b) else attr_b
            collisions[key] = {
                "entities": sorted({entity_a, entity_b}),
                "attribute": representative,
                "scores": {},
            }
        pair_key = f"{entity_a}.{attr_a}::{entity_b}.{attr_b}"
        collisions[key]["scores"][pair_key] = round(score, 3)

    return list(collisions.values())


def uncovered_terms(model: dict) -> List[Dict]:
    """Return ontology entities/attributes not represented in the model."""

    results: List[Dict] = []
    entities = model.get("entities", [])
    if not isinstance(entities, list):
        entities = []

    present_entities: Dict[str, dict] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        canonical = canonical_entity_name(name)
        present_entities[canonical] = entity

    for canonical, meta in ONTOLOGY["entities"].items():
        preferred_attrs = meta.get("preferred_attributes", {})
        entity = present_entities.get(canonical)
        if entity is None:
            results.append(
                {
                    "entity": canonical,
                    "missing_attrs": sorted(preferred_attrs.keys()),
                    "reason": "ontology_gap",
                }
            )
            continue

        attributes = entity.get("attributes", [])
        observed: set[str] = set()
        if isinstance(attributes, dict):
            observed = {_normalise_name(name) for name in attributes.keys()}
        else:
            for attribute in attributes:
                if isinstance(attribute, dict):
                    attr_name = attribute.get("name")
                else:
                    attr_name = attribute
                if attr_name:
                    observed.add(_normalise_name(str(attr_name)))

        missing: List[str] = []
        for preferred, synonyms in preferred_attrs.items():
            candidates = [preferred, *synonyms]
            if not any(_normalise_name(candidate) in observed for candidate in candidates):
                missing.append(preferred)
        if missing:
            results.append(
                {
                    "entity": canonical,
                    "missing_attrs": sorted(missing),
                    "reason": "ontology_gap",
                }
            )

    return results


def naming_suggestions(model: dict) -> List[Dict]:
    """Suggest canonical names for attributes that match known synonyms."""

    suggestions: List[Dict] = []
    entities = model.get("entities", [])
    if not isinstance(entities, list):
        return suggestions

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_name = str(entity.get("name") or "").strip()
        if not entity_name:
            continue
        canonical = canonical_entity_name(entity_name)
        attributes = entity.get("attributes", [])
        attribute_items = []
        if isinstance(attributes, dict):
            attribute_items = [str(name) for name in attributes.keys()]
        else:
            for attribute in attributes:
                if isinstance(attribute, dict):
                    attr_name = attribute.get("name")
                else:
                    attr_name = attribute
                if attr_name:
                    attribute_items.append(str(attr_name))
        for attr_name in attribute_items:
            preferred = suggest_preferred_attr(canonical, attr_name)
            if preferred and _normalise_name(preferred) != _normalise_name(attr_name):
                suggestions.append(
                    {
                        "entity": entity_name,
                        "from": attr_name,
                        "to": preferred,
                    }
                )

    return suggestions


def mece_score(collisions: List[dict], uncovered: List[dict]) -> float:
    """Compute a lightweight MECE score from detected issues."""

    penalty = 0.5 * (len(collisions) / 10.0) + 0.5 * (len(uncovered) / 10.0)
    penalty = min(1.0, penalty)
    score = 1.0 - penalty
    return max(0.0, min(1.0, round(score, 4)))


def analyze_mece(model_json_str: str) -> Dict:
    """Return a MECE coverage analysis for the provided model JSON string."""

    model = parse_model(model_json_str)
    collisions = find_collisions(model)
    uncovered = uncovered_terms(model)
    suggestions = naming_suggestions(model)
    score = mece_score(collisions, uncovered)
    return {
        "collisions": collisions,
        "uncovered_terms": uncovered,
        "naming_suggestions": suggestions,
        "mece_score": score,
    }


__all__ = [
    "analyze_mece",
    "find_collisions",
    "list_entity_attrs",
    "mece_score",
    "naming_suggestions",
    "parse_model",
    "uncovered_terms",
]
