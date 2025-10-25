"""Blueprint exposing relationship inference APIs."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from src.models.db import get_db
from src.models.tables import Relationship
from src.services.relationship_inference import (
    RelationshipInferenceService,
    _APPROVED_STATUS,
    _MANUAL_STATUS,
    _REJECTED_STATUS,
)

bp = Blueprint("relationships_api", __name__, url_prefix="/api/relationships")


@bp.route("/infer", methods=["POST"])
def infer_relationships():
    """Infer relationships for the supplied domain."""

    payload = request.get_json(silent=True) or {}
    try:
        domain_id = int(payload.get("domain_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "domain_id must be provided"}), 400

    sources = payload.get("sources")
    if not isinstance(sources, list):
        return jsonify({"error": "sources must be an array"}), 400

    with get_db() as session:
        service = RelationshipInferenceService(session)
        try:
            relationships = service.infer_relationships(domain_id, sources)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

        result = {"relationships": [_serialize_relationship(rel) for rel in relationships]}

    return jsonify(result), 200


@bp.route("/<int:relationship_id>/approve", methods=["POST"])
def approve_relationship(relationship_id: int):
    """Approve an inferred relationship."""

    return _update_status(relationship_id, _APPROVED_STATUS)


@bp.route("/<int:relationship_id>/reject", methods=["POST"])
def reject_relationship(relationship_id: int):
    """Reject an inferred relationship."""

    return _update_status(relationship_id, _REJECTED_STATUS)


def _update_status(relationship_id: int, status: str):
    with get_db() as session:
        relationship = session.get(Relationship, relationship_id)
        if relationship is None:
            return jsonify({"error": "relationship not found"}), 404

        if relationship.inference_status == _MANUAL_STATUS and relationship.evidence_json is None:
            return (
                jsonify({"error": "relationship is managed manually and cannot be updated"}),
                400,
            )

        relationship.inference_status = status
        session.flush()
        payload = _serialize_relationship(relationship)

    return jsonify(payload), 200


def _serialize_relationship(relationship: Relationship) -> dict[str, Any]:
    evidence = relationship.evidence_json or {}
    data: dict[str, Any] = {
        "id": relationship.id,
        "domain_id": relationship.domain_id,
        "from_entity": getattr(relationship.from_entity, "name", None),
        "to_entity": getattr(relationship.to_entity, "name", None),
        "relationship_type": relationship.relationship_type,
        "description": relationship.description,
        "inference_status": relationship.inference_status,
        "evidence": evidence,
    }
    if evidence:
        coverage = evidence.get("coverage")
        if isinstance(coverage, (int, float)):
            data["coverage_percent"] = round(float(coverage) * 100, 2)
    return data


__all__ = ["bp"]
