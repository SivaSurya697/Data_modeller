"""Endpoints supporting draft generation and review."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import Attribute, ChangeSet, Domain, Entity, Mapping, Relationship
from src.services.llm_modeler import DraftResult, ModelingService
from src.services.model_analysis import classify_entity, extract_relationship_cardinality
from src.services.exporters.dictionary import emit_dictionary_md
from src.services.exporters.impact_md import emit_impact_md
from src.services.exporters.model_json import bump_version_str, emit_model
from src.services.exporters.plantuml import emit_plantuml
from src.services.validators import DraftRequest
from src.services import validators
from src.services.exporters.utils import prepare_artifact_path

bp = Blueprint("modeler", __name__, url_prefix="/modeler")
api_bp = Blueprint("model_api", __name__, url_prefix="/api/model")


def _json_error(message: str, status_code: int = 400, issues: list[str] | None = None):
    payload: dict[str, Any] = {"ok": False, "error": message}
    if issues:
        payload["issues"] = issues
    response = jsonify(payload)
    response.status_code = status_code
    return response


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
        "id": getattr(relationship, "id", None),
        "from_name": relationship.from_entity.name,
        "to_name": relationship.to_entity.name,
        "type": relationship.relationship_type,
        "description": relationship.description,
        "from_cardinality": left,
        "to_cardinality": right,
        "evidence": getattr(relationship, "evidence_json", None),
        "inference_status": getattr(relationship, "inference_status", "manual"),
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


@api_bp.post("/publish")
def publish_model() -> Any:
    """Publish a reviewed model draft."""

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json_error("Invalid JSON body.")

    domain_name = str(payload.get("domain") or "").strip()
    if not domain_name:
        return _json_error("Domain name is required.")

    model_json_str = payload.get("model_json")
    if not isinstance(model_json_str, str) or not model_json_str.strip():
        return _json_error("'model_json' must be a non-empty JSON string.")

    changeset_id_raw = payload.get("changeset_id")
    if changeset_id_raw is None:
        changeset_id = None
    else:
        try:
            changeset_id = int(changeset_id_raw)
        except (TypeError, ValueError):
            return _json_error("'changeset_id' must be an integer.")

    force = bool(payload.get("force", False))
    approved = bool(payload.get("approved", False))

    validation = validators.validate_model_json(model_json_str)
    if not validation.get("ok", False):
        return _json_error("Model validation failed.", issues=validation.get("issues", []))

    with get_db() as session:
        domain_stmt = (
            select(Domain)
            .options(
                joinedload(Domain.entities).joinedload(Entity.attributes),
                joinedload(Domain.relationships)
                .joinedload(Relationship.from_entity),
                joinedload(Domain.relationships)
                .joinedload(Relationship.to_entity),
            )
            .where(Domain.name == domain_name)
        )
        domain = session.execute(domain_stmt).unique().scalar_one_or_none()
        if domain is None:
            return _json_error("Domain not found.", status_code=404)

        changeset: ChangeSet | None = None
        if changeset_id is not None:
            changeset = session.get(ChangeSet, changeset_id)
            if changeset is None:
                return _json_error("Change set not found.", status_code=404)
            if getattr(changeset, "domain_id", None) != domain.id:
                return _json_error("Change set does not belong to the specified domain.")

        relationship_dicts = [
            {
                "from": rel.from_entity.name if rel.from_entity else "",
                "to": rel.to_entity.name if rel.to_entity else "",
                "type": rel.relationship_type or "",
                "description": rel.description or "",
            }
            for rel in domain.relationships
        ]

        mappings = list(
            session.execute(
                select(Mapping).join(Entity).where(Entity.domain_id == domain.id)
            ).scalars()
        )
        mapping_dicts = [
            {
                "attribute_id": mapping.attribute_id,
                "status": getattr(mapping.status, "value", str(mapping.status)),
            }
            for mapping in mappings
        ]

        try:
            quality = validators.quality_summary(
                model_json_str, mapping_dicts, relationship_dicts
            )
        except ValueError as exc:
            return _json_error(str(exc))

        mapping_pct = quality.get("mapping_pct")
        if mapping_pct is not None and mapping_pct < 0.85:
            return _json_error(
                f"Mapping completeness below threshold (need >= 0.85, got {mapping_pct:.2f})"
            )

        rel_coverage_pct = quality.get("rel_coverage_pct")
        if rel_coverage_pct is not None and rel_coverage_pct < 0.80:
            return _json_error(
                "Relationship coverage below threshold "
                f"(need >= 0.80, got {rel_coverage_pct:.2f})"
            )

        impact_items: list[dict[str, Any]] = []
        has_high_impact = any(
            str(item.get("impact_level", "")).lower() == "high" for item in impact_items
        )
        if has_high_impact and not (force or approved):
            return _json_error("High impact on shared dims requires approval")

        new_version = bump_version_str(domain.version)
        domain.version = new_version
        domain.status = "published"

        artifacts_dir = Path(current_app.config.get("ARTIFACTS_DIR", "outputs"))
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        token = domain_name.replace(" ", "_")

        model_filename = f"model_{token}_{new_version}.json"
        diagram_filename = f"diagram_{token}_{new_version}.puml"
        dictionary_filename = f"dictionary_{token}_{new_version}.md"
        impact_filename = f"impact_{token}_{new_version}.md"

        model_path = prepare_artifact_path(artifacts_dir, model_filename)
        diagram_path = prepare_artifact_path(artifacts_dir, diagram_filename)
        dictionary_path = prepare_artifact_path(artifacts_dir, dictionary_filename)
        impact_path = prepare_artifact_path(artifacts_dir, impact_filename)

        emit_model(model_json_str, str(model_path))
        emit_plantuml(model_json_str, str(diagram_path))
        emit_dictionary_md(model_json_str, str(dictionary_path))
        emit_impact_md(impact_items, str(impact_path))

        changeset_filename: str | None = None
        if changeset_id is not None:
            if hasattr(changeset, "state"):
                setattr(changeset, "state", "published")
            changeset_filename = f"changeset_{changeset_id}_{new_version}.json"
            changeset_path = prepare_artifact_path(artifacts_dir, changeset_filename)
            changeset_payload = {
                "id": changeset_id,
                "version": new_version,
                "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            changeset_path.write_text(
                json.dumps(changeset_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        artifacts = {
            "model_json": model_filename,
            "diagram_puml": diagram_filename,
            "dictionary_md": dictionary_filename,
            "impact_md": impact_filename,
        }
        if changeset_filename:
            artifacts["changeset_json"] = changeset_filename

        response_payload = {
            "ok": True,
            "domain": domain_name,
            "version": new_version,
            "artifacts": artifacts,
            "quality": quality,
        }

    return jsonify(response_payload)

