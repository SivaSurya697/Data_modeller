"""Relationship inference utilities.

The service analyses profiling metadata describing source tables and foreign
key matches.  It computes simple coverage metrics and stores the evidence on
``Relationship`` rows so that the UI can surface pending suggestions for user
review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.tables import Domain, Entity, Relationship

_PENDING_STATUS = "pending"
_APPROVED_STATUS = "approved"
_REJECTED_STATUS = "rejected"
_MANUAL_STATUS = "manual"


@dataclass(slots=True)
class ForeignKeyEvidence:
    """Evidence describing a foreign key relationship."""

    source: str
    column: str
    target: str
    target_column: str
    row_count: int
    match_count: int
    coverage: float

    @classmethod
    def from_mapping(cls, source: str, row_count: int, payload: Mapping[str, Any]) -> "ForeignKeyEvidence":
        target_table = str(payload.get("referenced_source") or payload.get("to_source") or "").strip()
        target_column = str(payload.get("referenced_column") or payload.get("to_column") or "id").strip()
        column = str(payload.get("column") or payload.get("from_column") or "").strip()
        match_count_raw = payload.get("match_count") or payload.get("matches") or 0
        try:
            match_count = max(int(match_count_raw), 0)
        except (TypeError, ValueError):
            match_count = 0
        coverage = 0.0
        if row_count > 0:
            coverage = round(min(match_count / row_count, 1.0), 6)
        return cls(
            source=source,
            column=column,
            target=target_table,
            target_column=target_column,
            row_count=row_count,
            match_count=match_count,
            coverage=coverage,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "column": self.column,
            "target": self.target,
            "target_column": self.target_column,
            "row_count": self.row_count,
            "match_count": self.match_count,
            "coverage": self.coverage,
        }


class RelationshipInferenceService:
    """Infer relationships from profiling metadata."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def infer_relationships(
        self, domain_id: int, sources: Sequence[Mapping[str, Any]]
    ) -> list[Relationship]:
        """Create or update pending relationships for ``domain_id``.

        Parameters
        ----------
        domain_id:
            Identifier of the domain being profiled.
        sources:
            Sequence of source profiling payloads.  Each entry is expected to
            provide a ``name`` and ``row_count`` with a ``foreign_keys`` list
            describing matches.
        """

        domain = self._session.get(Domain, domain_id)
        if domain is None:
            raise ValueError(f"Domain {domain_id} does not exist")

        entity_lookup = {
            entity.name.lower(): entity for entity in domain.entities if entity.name
        }

        inferred: list[Relationship] = []
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            source_name = str(source.get("name") or "").strip()
            if not source_name:
                continue
            row_count = self._coerce_int(source.get("row_count"))
            foreign_keys = source.get("foreign_keys")
            if not isinstance(foreign_keys, Iterable):
                continue

            from_entity = entity_lookup.get(source_name.lower())
            if from_entity is None:
                continue

            for fk_payload in foreign_keys:
                if not isinstance(fk_payload, Mapping):
                    continue
                evidence = ForeignKeyEvidence.from_mapping(source_name, row_count, fk_payload)
                to_entity = entity_lookup.get(evidence.target.lower())
                if to_entity is None:
                    continue
                relationship_type = str(
                    fk_payload.get("relationship_type")
                    or fk_payload.get("type")
                    or "inferred_foreign_key"
                ).strip() or "inferred_foreign_key"
                description = (
                    str(fk_payload.get("description") or "").strip() or None
                )

                relationship = self._get_or_create_relationship(
                    domain_id, from_entity, to_entity, relationship_type
                )
                if relationship.inference_status == _MANUAL_STATUS and relationship.evidence_json is None:
                    # Skip manual relationships when no inference metadata exists.
                    continue

                relationship.description = description or relationship.description
                relationship.evidence_json = evidence.to_payload()
                if relationship.inference_status == _MANUAL_STATUS:
                    relationship.inference_status = _PENDING_STATUS
                elif relationship.inference_status == _REJECTED_STATUS:
                    relationship.inference_status = _PENDING_STATUS

                inferred.append(relationship)

        self._session.flush()
        return inferred

    def _get_or_create_relationship(
        self,
        domain_id: int,
        from_entity: Entity,
        to_entity: Entity,
        relationship_type: str,
    ) -> Relationship:
        stmt = select(Relationship).where(
            Relationship.domain_id == domain_id,
            Relationship.from_entity_id == from_entity.id,
            Relationship.to_entity_id == to_entity.id,
            Relationship.relationship_type == relationship_type,
        )
        existing = self._session.execute(stmt).scalars().first()
        if existing:
            return existing

        relationship = Relationship(
            domain_id=domain_id,
            from_entity=from_entity,
            to_entity=to_entity,
            relationship_type=relationship_type,
            inference_status=_PENDING_STATUS,
        )
        self._session.add(relationship)
        return relationship

    @staticmethod
    def _coerce_int(value: Any) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return 0


__all__ = [
    "ForeignKeyEvidence",
    "RelationshipInferenceService",
    "_APPROVED_STATUS",
    "_PENDING_STATUS",
    "_REJECTED_STATUS",
    "_MANUAL_STATUS",
]
