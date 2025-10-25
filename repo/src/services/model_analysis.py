"""Utilities for classifying entities and interpreting relationship details."""

from __future__ import annotations

import re
from typing import Literal, Sequence

from src.models.tables import DataModel, Domain, Entity, Relationship

EntityCategory = Literal["fact", "dimension", "other"]

_FACT_KEYWORDS = {
    "fact",
    "facts",
    "facttable",
    "facttables",
    "measure",
    "measures",
    "metric",
    "metrics",
    "event",
    "events",
}

_DIMENSION_KEYWORDS = {
    "dimension",
    "dimensions",
    "dim",
    "lookup",
    "lookups",
    "attribute",
    "attributes",
    "hierarchy",
    "hierarchies",
    "reference",
    "references",
}

_TYPE_HINT_PATTERN = re.compile(r"\b(?:type|classification|entity\s+type)\s*[:=]\s*(?P<label>[a-z\s]+)")


def _tokenize(text: str) -> list[str]:
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return [token for token in tokens if token]


def _has_keyword(tokens: Sequence[str], keywords: set[str]) -> bool:
    return any(token in keywords for token in tokens)


def _has_type_hint(text: str, keyword: str) -> bool:
    for match in _TYPE_HINT_PATTERN.finditer(text.lower()):
        label = match.group("label").strip()
        simplified = label.replace(" table", "").replace(" entity", "")
        if keyword in {label, simplified}:
            return True
    return False


def classify_entity(entity: Entity) -> EntityCategory:
    """Return the inferred classification for ``entity``."""

    name = entity.name or ""
    description = entity.description or ""
    documentation = entity.documentation or ""
    combined = " ".join(part for part in (name, description, documentation) if part)

    tokens = _tokenize(combined)
    if _has_keyword(tokens, _FACT_KEYWORDS) or _has_type_hint(combined, "fact"):
        return "fact"
    if _has_keyword(tokens, _DIMENSION_KEYWORDS) or _has_type_hint(combined, "dimension"):
        return "dimension"
    return "other"


_CARDINALITY_PATTERNS: list[tuple[tuple[re.Pattern[str], ...], tuple[str, str]]] = [
    (
        (
            re.compile(r"\b(one|1)\s*(?:-|:|\s+to\s+)\s*(many|\*|n|m)\b"),
            re.compile(r"\b1\s*\.\.\s*(?:\*|n|m)\b"),
        ),
        ("1", "*"),
    ),
    (
        (
            re.compile(r"\b(many|\*|n|m)\s*(?:-|:|\s+to\s+)\s*(one|1)\b"),
            re.compile(r"\b(?:\*|n|m)\s*\.\.\s*1\b"),
        ),
        ("*", "1"),
    ),
    (
        (
            re.compile(r"\b(many|\*|n|m)\s*(?:-|:|\s+to\s+)\s*(many|\*|n|m)\b"),
            re.compile(r"\b(?:\*|n|m)\s*\.\.\s*(?:\*|n|m)\b"),
        ),
        ("*", "*"),
    ),
    (
        (
            re.compile(r"\b(one|1)\s*(?:-|:|\s+to\s+)\s*(one|1)\b"),
            re.compile(r"\b1\s*\.\.\s*1\b"),
        ),
        ("1", "1"),
    ),
]


def extract_relationship_cardinality(relationship: Relationship) -> tuple[str | None, str | None]:
    """Infer the relationship cardinality from type/description metadata."""

    parts = [relationship.relationship_type or ""]
    if relationship.description:
        parts.append(relationship.description)
    text = " ".join(parts).lower()
    normalized = re.sub(r"[–—]", "-", text)
    normalized = normalized.replace("-to-", " to ")

    for regexes, cardinality in _CARDINALITY_PATTERNS:
        for regex in regexes:
            if regex.search(normalized):
                return cardinality
    ratio_match = re.search(r"\b(0|1|\*|n|m)\s*[:]\s*(0|1|\*|n|m)\b", normalized)
    if ratio_match:
        left = _normalize_ratio_token(ratio_match.group(1))
        right = _normalize_ratio_token(ratio_match.group(2))
        return left, right
    return None, None


def _normalize_ratio_token(token: str) -> str:
    token = token.strip()
    if token in {"n", "m", "*"}:
        return "*"
    return token or "*"


def infer_model_version(domain: Domain) -> int:
    """Return the best-effort model version for ``domain``."""

    models_attr = getattr(domain, "models", None)
    if not models_attr:
        return 1

    count = sum(1 for model in models_attr if isinstance(model, DataModel))
    return count or 1


__all__ = [
    "EntityCategory",
    "classify_entity",
    "extract_relationship_cardinality",
    "infer_model_version",
]
