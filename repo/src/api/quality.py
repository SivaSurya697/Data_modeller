"""Endpoints and views presenting model quality metrics."""

from __future__ import annotations

import json
from typing import Any

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import Domain, Entity, Mapping, Relationship
from src.services.coverage_analyzer import CoverageAnalyzer
from src.services.validators import quality_summary as compute_quality_summary

bp = Blueprint("quality_api", __name__)
ui_bp = Blueprint("quality", __name__, url_prefix="/quality")


def _normalise_grain(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def _serialise_model(domain: Domain) -> str:
    entities_payload: list[dict[str, Any]] = []
    for entity in sorted(domain.entities, key=lambda item: item.name.lower()):
        attributes_payload: list[dict[str, Any]] = []
        for attribute in sorted(entity.attributes, key=lambda item: item.name.lower()):
            attributes_payload.append(
                {
                    "id": attribute.id,
                    "name": attribute.name,
                    "data_type": attribute.data_type,
                    "description": attribute.description,
                    "is_nullable": attribute.is_nullable,
                    "default": attribute.default_value,
                    "is_measure": attribute.is_measure,
                    "is_surrogate_key": attribute.is_surrogate_key,
                }
            )

        entities_payload.append(
            {
                "id": entity.id,
                "name": entity.name,
                "description": entity.description,
                "documentation": entity.documentation,
                "role": entity.role.value if entity.role else None,
                "grain": _normalise_grain(getattr(entity, "grain_json", None)),
                "scd_type": entity.scd_type.value if entity.scd_type else None,
                "attributes": attributes_payload,
                "keys": [],
            }
        )

    relationships_payload: list[dict[str, Any]] = []
    for relationship in domain.relationships:
        relationships_payload.append(
            {
                "from": relationship.from_entity.name if relationship.from_entity else None,
                "to": relationship.to_entity.name if relationship.to_entity else None,
                "type": relationship.relationship_type,
            }
        )

    model_payload = {"entities": entities_payload}
    if relationships_payload:
        model_payload["relationships"] = relationships_payload
    return json.dumps(model_payload)


@bp.get("/summary")
def summary():  # pragma: no cover - exercised via integration
    """Return model quality metrics for the requested domain."""

    domain_name = str(request.args.get("domain") or "").strip()
    if not domain_name:
        return jsonify({"ok": False, "error": "Query parameter 'domain' is required."}), 400

    request_payload = request.get_json(silent=True) or {}
    model_json_override = request_payload.get("model_json")
    model_json_str: str | None = None
    if isinstance(model_json_override, dict):
        model_json_str = json.dumps(model_json_override)
    elif isinstance(model_json_override, str) and model_json_override.strip():
        model_json_str = model_json_override

    mappings_payload: list[dict[str, Any]] | None = None
    relationships_payload: list[dict[str, Any]] | None = None

    with get_db() as session:
        stmt = (
            select(Domain)
            .options(
                joinedload(Domain.entities).joinedload(Entity.attributes),
                joinedload(Domain.relationships).joinedload(Relationship.from_entity),
                joinedload(Domain.relationships).joinedload(Relationship.to_entity),
            )
            .where(Domain.name == domain_name)
        )
        domain = session.execute(stmt).scalar_one_or_none()

        if domain is not None:
            if model_json_str is None:
                model_json_str = _serialise_model(domain)

            relationships_payload = [
                {
                    "from": rel.from_entity.name if rel.from_entity else None,
                    "to": rel.to_entity.name if rel.to_entity else None,
                    "type": rel.relationship_type,
                }
                for rel in domain.relationships
            ]

            mappings_stmt = (
                select(Mapping)
                .join(Entity, Mapping.entity_id == Entity.id)
                .where(Entity.domain_id == domain.id)
            )
            mappings_payload = [
                {
                    "attribute_id": mapping.attribute_id,
                    "status": mapping.status.value,
                    "source_table_id": mapping.source_table_id,
                }
                for mapping in session.execute(mappings_stmt).scalars()
            ]

    if model_json_str is None:
        return jsonify({"ok": False, "error": "Model JSON must be provided."}), 400

    try:
        summary_payload = compute_quality_summary(
            model_json_str,
            mappings=mappings_payload,
            relationships=relationships_payload,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "summary": summary_payload})


@ui_bp.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    """Render the quality dashboard with ontology coverage metrics."""

    analyzer = CoverageAnalyzer()
    selected_domain_id = request.values.get("domain_id")

    with get_db() as session:
        domains = list(session.scalars(select(Domain).order_by(Domain.name)))
        if not domains:
            flash("No domains available to analyze.", "warning")
            return render_template(
                "quality_dashboard.html",
                domains=domains,
                selected_domain_id=None,
                report=None,
            )

        if selected_domain_id is None:
            selected_domain_id = str(domains[0].id)

        try:
            domain_id = int(selected_domain_id)
        except ValueError:
            flash("Invalid domain selected for analysis.", "error")
            return redirect(url_for("quality.dashboard"))

        try:
            report = analyzer.analyze_domain(session, domain_id)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("quality.dashboard"))

    return render_template(
        "quality_dashboard.html",
        domains=domains,
        selected_domain_id=domain_id,
        report=report,
    )


__all__ = ["bp", "ui_bp"]
