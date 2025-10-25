"""Analyze ontology coverage for domain models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.models.tables import Attribute, Domain, Entity
from src.services.ontology import Ontology, get_default_ontology


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Aggregate the coverage analysis results."""

    domain_id: int
    domain_name: str
    entity_overlaps: tuple[str, ...]
    attribute_overlaps: tuple[str, ...]
    entity_collisions: tuple[str, ...]
    attribute_collisions: tuple[str, ...]
    uncovered_entities: tuple[str, ...]
    uncovered_attributes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "domain_id": self.domain_id,
            "domain_name": self.domain_name,
            "entity_overlaps": list(self.entity_overlaps),
            "attribute_overlaps": list(self.attribute_overlaps),
            "entity_collisions": list(self.entity_collisions),
            "attribute_collisions": list(self.attribute_collisions),
            "uncovered_entities": list(self.uncovered_entities),
            "uncovered_attributes": list(self.uncovered_attributes),
        }


class CoverageAnalyzer:
    """Service comparing a domain model against the ontology."""

    def __init__(self, ontology: Ontology | None = None) -> None:
        self._ontology = ontology or get_default_ontology()

    def analyze_domain(self, session: Session, domain_id: int) -> CoverageReport:
        domain = (
            session.execute(
                select(Domain)
                .where(Domain.id == domain_id)
                .options(joinedload(Domain.entities).joinedload(Entity.attributes))
            )
            .scalars()
            .unique()
            .one_or_none()
        )
        if domain is None:
            raise ValueError("Domain not found")

        domain_entities = {entity.name.strip(): entity for entity in domain.entities}
        domain_attributes = {
            attribute.name.strip(): attribute
            for attribute in self._iter_attributes(domain.entities)
        }

        ontology_entities = {
            name: item.name for name, item in self._ontology.entities.items()
        }
        ontology_attributes = {
            name: item.name for name, item in self._ontology.attributes.items()
        }

        entity_name_map = self._normalise_map(domain_entities.keys())
        attribute_name_map = self._normalise_map(domain_attributes.keys())

        entity_overlaps = self._compute_overlaps(entity_name_map, ontology_entities)
        attribute_overlaps = self._compute_overlaps(
            attribute_name_map, ontology_attributes
        )

        entity_collisions = self._compute_collisions(entity_name_map, ontology_entities)
        attribute_collisions = self._compute_collisions(
            attribute_name_map, ontology_attributes
        )

        uncovered_entities = self._compute_gaps(entity_name_map, ontology_entities)
        uncovered_attributes = self._compute_gaps(
            attribute_name_map, ontology_attributes
        )

        return CoverageReport(
            domain_id=domain.id,
            domain_name=domain.name,
            entity_overlaps=entity_overlaps,
            attribute_overlaps=attribute_overlaps,
            entity_collisions=entity_collisions,
            attribute_collisions=attribute_collisions,
            uncovered_entities=uncovered_entities,
            uncovered_attributes=uncovered_attributes,
        )

    def _iter_attributes(self, entities: Iterable[Entity]) -> Iterable[Attribute]:
        for entity in entities:
            yield from entity.attributes

    def _compute_overlaps(
        self, domain_names: dict[str, str], ontology_names: dict[str, str]
    ) -> tuple[str, ...]:
        overlaps = {
            ontology_names[name_key]
            for name_key in domain_names
            if name_key in ontology_names
        }
        return tuple(sorted(overlaps))

    def _compute_collisions(
        self, domain_names: dict[str, str], ontology_names: dict[str, str]
    ) -> tuple[str, ...]:
        collisions = {
            original
            for name_key, original in domain_names.items()
            if name_key not in ontology_names
        }
        return tuple(sorted(collisions))

    def _compute_gaps(
        self, domain_names: dict[str, str], ontology_names: dict[str, str]
    ) -> tuple[str, ...]:
        missing = {
            canonical
            for normalised, canonical in ontology_names.items()
            if normalised not in domain_names
        }
        return tuple(sorted(missing))

    @staticmethod
    def _normalise_map(values: Iterable[str]) -> dict[str, str]:
        return {value.strip().lower(): value for value in values}


__all__ = ["CoverageAnalyzer", "CoverageReport"]
