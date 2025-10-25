"""Ontology loading utilities used by prompts and validation layers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class OntologyAttribute:
    """Canonical attribute definition within the ontology."""

    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class OntologyEntity:
    """Canonical entity definition within the ontology."""

    name: str
    description: str | None = None
    attributes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Ontology:
    """Immutable container for ontology definitions."""

    entities: dict[str, OntologyEntity]
    attributes: dict[str, OntologyAttribute]

    def entity_names(self) -> Iterable[str]:
        return self.entities.keys()

    def attribute_names(self) -> Iterable[str]:
        return self.attributes.keys()


def _default_seed_path() -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "context" / "ontology_seed.json"


def _normalise_key(value: str) -> str:
    return value.strip().lower()


def load_ontology(path: Path | None = None) -> Ontology:
    """Load an ontology description from disk."""

    ontology_path = path or _default_seed_path()
    if not ontology_path.exists():
        raise FileNotFoundError(f"Ontology seed file not found: {ontology_path}")

    raw = json.loads(ontology_path.read_text(encoding="utf-8"))

    entity_entries = {
        _normalise_key(item["name"]): OntologyEntity(
            name=item["name"].strip(),
            description=item.get("description"),
            attributes=tuple(attr.strip() for attr in item.get("attributes", [])),
        )
        for item in raw.get("entities", [])
    }

    attribute_entries = {
        _normalise_key(item["name"]): OntologyAttribute(
            name=item["name"].strip(),
            description=item.get("description"),
        )
        for item in raw.get("attributes", [])
    }

    return Ontology(entities=entity_entries, attributes=attribute_entries)


@lru_cache(maxsize=1)
def get_default_ontology() -> Ontology:
    """Return the ontology seeded with the repository default."""

    return load_ontology()


__all__ = [
    "Ontology",
    "OntologyAttribute",
    "OntologyEntity",
    "get_default_ontology",
    "load_ontology",
]
