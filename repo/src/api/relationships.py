"""API endpoints for inferred relationships."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from flask import Blueprint, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import Domain, Relationship
from src.services.relationship_inference import (
    RelationshipInferenceService,
    _APPROVED_STATUS,
    _REJECTED_STATUS,
)

bp = Blueprint("relationships", __name__)


def _parse_domain_id(value: Any) -> int | None:
    try:
        domain_id = int(value)
    except (TypeError, ValueError):
        return None
    return domain_id if domain_id > 0 else None


def _serialise_relationship(relationship: Relationship) -> dict[str, Any]:
    evidence = relationship.evidence_json or {}
    payload: dict[str, Any] = {
        "id": relationship.id,
        "from": getattr(relationship.from_entity, "name", None),
        "to": getattr(relationship.to_entity, "name", None),
        "type": relationship.relationship_type,
        "rule": relationship.description,
        "inference_status": relationship.inference_status,
        "evidence": evidence,
    }
    if isinstance(evidence, Mapping):
        coverage = evidence.get("coverage")
        if isinstance(coverage, (int, float)):
            payload["coverage_percent"] = round(float(coverage) * 100.0, 2)
    return payload


@bp.post("/infer")
def infer_relationships() -> Any:
    """Infer relationships from profiler metadata and persist them as pending."""

    payload = request.get_json(silent=True) or {}
    domain_id = _parse_domain_id(payload.get("domain_id"))
    if domain_id is None:
        return jsonify({"error": "domain_id must be a positive integer"}), 400

    sources = payload.get("sources")
    if sources is None:
        sources = []
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        return jsonify({"error": "sources must be an array"}), 400

    with get_db() as session:
        service = RelationshipInferenceService(session)
        try:
            relationships = service.infer_relationships(domain_id, list(sources))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

        data = [_serialise_relationship(relationship) for relationship in relationships]

    return jsonify({"relationships": data})


def _update_status(relationship_id: int, status: str) -> tuple[dict[str, Any], int]:
    with get_db() as session:
        relationship = session.execute(
            select(Relationship)
            .options(
                joinedload(Relationship.from_entity),
                joinedload(Relationship.to_entity),
            )
            .where(Relationship.id == relationship_id)
        ).scalar_one_or_none()
        if relationship is None:
            return {"error": "relationship not found"}, 404

        relationship.inference_status = status
        session.flush()
        return _serialise_relationship(relationship), 200


@bp.post("/<int:relationship_id>/approve")
def approve_relationship(relationship_id: int) -> Any:
    """Mark an inferred relationship as approved."""

    payload, status = _update_status(relationship_id, _APPROVED_STATUS)
    return jsonify(payload), status


@bp.post("/<int:relationship_id>/reject")
def reject_relationship(relationship_id: int) -> Any:
    """Mark an inferred relationship as rejected."""

    payload, status = _update_status(relationship_id, _REJECTED_STATUS)
    return jsonify(payload), status


@bp.get("/")
def list_relationships() -> Any:
    """Return relationships for a domain."""

    domain_param = request.args.get("domain_id") or request.args.get("domain")
    domain_id = _parse_domain_id(domain_param)
    domain_name = request.args.get("domain_name") if domain_id is None else None

    with get_db() as session:
        stmt = select(Relationship).options(
            joinedload(Relationship.from_entity),
            joinedload(Relationship.to_entity),
        )
        if domain_id is not None:
            stmt = stmt.where(Relationship.domain_id == domain_id)
        elif domain_name:
            domain = session.execute(
                select(Domain).where(Domain.name == domain_name)
            ).scalar_one_or_none()
            if domain is None:
                return jsonify({"error": f"Domain '{domain_name}' was not found"}), 404
            stmt = stmt.where(Relationship.domain_id == domain.id)
        relationships = session.execute(stmt).unique().scalars().all()

        data = [_serialise_relationship(relationship) for relationship in relationships]

    return jsonify({"relationships": data})


__all__ = ["bp"]
