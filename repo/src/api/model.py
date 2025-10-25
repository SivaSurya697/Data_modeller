"""Endpoints supporting draft generation and review."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select

from src.models.db import get_db
from src.models.tables import Attribute, Domain, Entity, Relationship
from src.services.llm_modeler import DraftResult, ModelingService
from src.services.model_analysis import classify_entity, extract_relationship_cardinality
from src.services.publish import PublishBlocked, PublishService
from src.services.validators import DraftRequest

bp = Blueprint("modeler", __name__, url_prefix="/modeler")
api_bp = Blueprint("model_api", __name__, url_prefix="/api/model")


def _load_domains() -> list[Domain]:
    with get_db() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())
    return domains


def _serialize_attribute(attribute: Attribute) -> dict[str, object]:
    return {
        "name": attribute.name,
        "data_type": attribute.data_type,
        "description": attribute.description,
        "is_nullable": attribute.is_nullable,
    }


def _serialize_entity(entity: Entity) -> dict[str, object]:
    return {
        "name": entity.name,
        "description": entity.description,
        "documentation": entity.documentation,
        "attributes": [
            _serialize_attribute(attribute)
            for attribute in sorted(entity.attributes, key=lambda item: item.name.lower())
        ],
    }


def _serialize_relationship(relationship: Relationship) -> dict[str, object]:
    left, right = extract_relationship_cardinality(relationship)
    return {
        "from_name": relationship.from_entity.name,
        "to_name": relationship.to_entity.name,
        "type": relationship.relationship_type,
        "description": relationship.description,
        "from_cardinality": left,
        "to_cardinality": right,
    }


def _build_draft_view_model(result: DraftResult) -> dict[str, object]:
    facts: list[dict[str, object]] = []
    dimensions: list[dict[str, object]] = []
    others: list[dict[str, object]] = []

    for entity in sorted(result.entities, key=lambda item: item.name.lower()):
        serialized = _serialize_entity(entity)
        classification = classify_entity(entity)
        if classification == "fact":
            facts.append(serialized)
        elif classification == "dimension":
            dimensions.append(serialized)
        else:
            others.append(serialized)

    relationships = [_serialize_relationship(rel) for rel in result.relationships]

    return {
        "model": result.model,
        "version": result.version,
        "facts": facts,
        "dimensions": dimensions,
        "other_entities": others,
        "relationships": relationships,
        "impact": result.impact,
    }


@bp.route("/draft", methods=["GET", "POST"])
def draft_review():
    """Render the draft review screen and handle draft requests."""

    draft = None
    if request.method == "POST":
        try:
            payload = DraftRequest(**request.form)
        except ValidationError as exc:
            flash(f"Invalid input: {exc}", "error")
            return redirect(url_for("modeler.draft_review"))

        service = ModelingService()
        try:
            with get_db() as session:
                result = service.generate_draft(session, payload)
                draft = _build_draft_view_model(result)
            flash("Draft generated successfully.", "success")
        except Exception as exc:  # pragma: no cover - surface to UI
            flash(f"Draft generation failed: {exc}", "error")
            return redirect(url_for("modeler.draft_review"))

    domains = _load_domains()
    return render_template("draft_review.html", domains=domains, draft=draft)


@api_bp.route("/publish", methods=["POST"])
def publish_model() -> tuple[dict[str, object], int] | tuple[str, int]:
    """Trigger the publish workflow for a domain."""

    payload = request.get_json(silent=True) or {}
    domain_id = payload.get("domain_id")
    version_tag = payload.get("version_tag")

    if domain_id is None:
        return jsonify({"message": "'domain_id' is required."}), 400

    try:
        domain_id_int = int(domain_id)
    except (TypeError, ValueError):
        return jsonify({"message": "'domain_id' must be an integer."}), 400

    artifacts_dir = Path(current_app.config["ARTIFACTS_DIR"])
    service = PublishService(artifacts_dir)

    with get_db() as session:
        domain = session.get(Domain, domain_id_int)
        if domain is None:
            return jsonify({"message": "Domain not found."}), 404

        try:
            result = service.publish(session, domain, version_tag=version_tag)
        except PublishBlocked as blocked:
            return (
                jsonify(
                    {
                        "message": "Publication blocked by quality gates.",
                        "preview": blocked.preview.to_dict(),
                    }
                ),
                400,
            )
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400

        response = result.to_dict()
        return jsonify(response), 200

