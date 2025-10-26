"""Endpoints supporting draft generation and review."""

from __future__ import annotations

import json
from typing import Any, Mapping as MappingType
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
from src.models.tables import (
    Attribute,
    ChangeItem,
    ChangeSet,
    Domain,
    Entity,
    Mapping as MappingTable,
    Relationship,
)
from src.services import diff_helpers
from src.services.llm_modeler import DraftResult, ModelingService, draft_extend
from src.services.model_analysis import classify_entity, extract_relationship_cardinality
from src.services.model_store import load_latest_model_json
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


def _normalise_grain(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


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
    model_entities: list[dict[str, object]] = []

    def _entity_sort_key(item: Any) -> str:
        return str(getattr(item, "name", "")).lower()

    for entity in sorted(result.entities, key=_entity_sort_key):
        serialized = _serialize_entity(entity)
        classification = classify_entity(entity)
        if classification == "fact":
            facts.append(serialized)
        elif classification == "dimension":
            dimensions.append(serialized)
        else:
            others.append(serialized)

        attribute_payloads = []
        for attribute in sorted(
            getattr(entity, "attributes", []),
            key=lambda item: str(getattr(item, "name", "")).lower(),
        ):
            name = str(getattr(attribute, "name", ""))
            attribute_payloads.append(
                {
                    "id": getattr(attribute, "id", None),
                    "name": name,
                    "data_type": getattr(attribute, "data_type", None),
                    "description": getattr(attribute, "description", None),
                    "is_nullable": bool(getattr(attribute, "is_nullable", True)),
                    "default": getattr(attribute, "default_value", getattr(attribute, "default", None)),
                    "is_measure": bool(getattr(attribute, "is_measure", False)),
                    "is_surrogate_key": bool(
                        getattr(attribute, "is_surrogate_key", False)
                    ),
                }
            )

        role = getattr(entity, "role", None)
        if role is not None and hasattr(role, "value"):
            role_value = role.value
        elif role is not None:
            role_value = str(role)
        else:
            role_value = None

        scd_type = getattr(entity, "scd_type", None)
        if scd_type is not None and hasattr(scd_type, "value"):
            scd_type_value = scd_type.value
        elif scd_type is not None:
            scd_type_value = str(scd_type)
        else:
            scd_type_value = None

        model_entity = {
            "id": getattr(entity, "id", None),
            "name": getattr(entity, "name", None),
            "description": getattr(entity, "description", None),
            "documentation": getattr(entity, "documentation", None),
            "role": role_value,
            "grain": _normalise_grain(getattr(entity, "grain_json", None)),
            "scd_type": scd_type_value,
            "attributes": attribute_payloads,
            "keys": [],
        }
        model_entities.append(model_entity)

    relationships = [_serialize_relationship(rel) for rel in result.relationships]

    model_relationships = [
        {
            "from": rel.from_entity.name if rel.from_entity else None,
            "to": rel.to_entity.name if rel.to_entity else None,
            "type": rel.relationship_type,
        }
        for rel in result.relationships
    ]

    model_obj = getattr(result, "model", None)
    model_payload: dict[str, Any] = {
        "name": getattr(model_obj, "name", "Draft Model"),
        "summary": getattr(model_obj, "summary", ""),
        "entities": model_entities,
    }
    if model_relationships:
        model_payload["relationships"] = model_relationships

    return {
        "model": result.model,
        "version": result.version,
        "facts": facts,
        "dimensions": dimensions,
        "other_entities": others,
        "relationships": relationships,
        "impact": result.impact,
        "model_json": json.dumps(model_payload, ensure_ascii=False),
    }


def _infer_object_type(action: str, item: MappingType[str, Any]) -> str:
    """Return a normalised object type hint for a change item."""

    hint = str(item.get("object_type") or "").strip().lower()
    if hint in {"entity", "relationship", "logical_model"}:
        return hint
    action_text = action.lower()
    if "relationship" in action_text:
        return "relationship"
    if "entity" in action_text:
        return "entity"
    return "logical_model"


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, MappingType):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, MappingType):
            return dict(parsed)
    return {}


def _extract_before_payload(
    baseline_json: str,
    *,
    object_type: str,
    action: str,
    target: str,
    item: MappingType[str, Any],
    after_json: MappingType[str, Any] | None,
) -> dict[str, Any]:
    action_text = action.lower()
    if object_type == "entity" and ("update" in action_text or "delete" in action_text):
        entity = diff_helpers.extract_entity_by_name(baseline_json, target)
        if entity:
            return entity
    if object_type == "relationship" and ("update" in action_text or "delete" in action_text):
        from_name = str(
            item.get("from")
            or item.get("from_name")
            or item.get("source")
            or ""
        ).strip()
        to_name = str(
            item.get("to")
            or item.get("to_name")
            or item.get("target_entity")
            or ""
        ).strip()
        if after_json:
            from_name = from_name or str(
                after_json.get("from")
                or after_json.get("source")
                or after_json.get("from_entity")
                or after_json.get("from_name")
                or ""
            ).strip()
            to_name = to_name or str(
                after_json.get("to")
                or after_json.get("target")
                or after_json.get("to_entity")
                or after_json.get("to_name")
                or ""
            ).strip()
        if (not from_name or not to_name) and "->" in target:
            left, right = (part.strip() for part in target.split("->", 1))
            from_name = from_name or left
            to_name = to_name or right
        if from_name and to_name:
            relationship = diff_helpers.extract_relationship_by_pair(
                baseline_json, from_name, to_name
            )
            if relationship:
                return relationship
    return {}


@api_bp.post("/extend")
def extend_model() -> Any:
    """Invoke the LLM extend prompt and persist the resulting change set."""

    payload_raw = request.get_json(silent=True)
    if not isinstance(payload_raw, MappingType):
        payload_raw = {}

    domain_name = str(payload_raw.get("domain") or "").strip()
    if not domain_name:
        return (
            jsonify({"ok": False, "error": "Domain name is required."}),
            400,
        )

    artifacts_dir = current_app.config.get("ARTIFACTS_DIR", "outputs")
    baseline_json = load_latest_model_json(artifacts_dir, domain_name)
    if baseline_json is None:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "No published model found for domain; publish once before extend.",
                }
            ),
            400,
        )

    try:
        creator_id = int(payload_raw.get("user_id", 1))
    except (TypeError, ValueError):
        creator_id = 1

    with get_db() as session:
        domain = session.execute(
            select(Domain).where(Domain.name == domain_name)
        ).scalar_one_or_none()
        if domain is None:
            return jsonify({"ok": False, "error": "Domain not found."}), 404

        try:
            diff_raw = draft_extend(
                session,
                domain=domain_name,
                prior_excerpt_json=baseline_json,
                user_id=creator_id,
            )
        except Exception:  # pragma: no cover - defensive logging
            current_app.logger.exception(
                "Failed to generate extension diff for domain %s", domain_name
            )
            return (
                jsonify({"ok": False, "error": "Failed to generate extension diff."}),
                500,
            )

        try:
            diff_payload_raw = json.loads(diff_raw)
        except json.JSONDecodeError:
            return (
                jsonify({"ok": False, "error": "LLM response was not valid JSON."}),
                400,
            )

        if not isinstance(diff_payload_raw, MappingType):
            return (
                jsonify({"ok": False, "error": "LLM diff must be a JSON object."}),
                400,
            )

        proposed_changes_raw = diff_payload_raw.get("proposed_changes")
        if not isinstance(proposed_changes_raw, list):
            return (
                jsonify(
                    {"ok": False, "error": "LLM diff missing 'proposed_changes' list."}
                ),
                400,
            )

        dictionary_updates_raw = diff_payload_raw.get("dictionary_updates")
        if not isinstance(dictionary_updates_raw, list):
            dictionary_updates_raw = []

        changeset_id_value = payload_raw.get("changeset_id")
        if changeset_id_value is not None:
            try:
                change_set_id = int(changeset_id_value)
            except (TypeError, ValueError):
                return (
                    jsonify({"ok": False, "error": "changeset_id must be an integer."}),
                    400,
                )
            change_set = session.get(ChangeSet, change_set_id)
            if change_set is None:
                return jsonify({"ok": False, "error": "ChangeSet not found."}), 404
            if change_set.domain_id != domain.id:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "ChangeSet belongs to a different domain.",
                        }
                    ),
                    400,
                )
            if change_set.state not in {"draft", "in_review"}:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "ChangeSet must be in draft or in_review state.",
                        }
                    ),
                    400,
                )
            change_set.items.clear()
            session.flush()
        else:
            change_set = ChangeSet(
                domain=domain,
                title=f"Extend {domain_name}",
                summary="Proposed model extension generated from LLM diff.",
                state="draft",
                created_by=creator_id,
            )
            session.add(change_set)
            session.flush()

        sanitized_changes: list[dict[str, Any]] = []
        change_count = 0
        for entry in proposed_changes_raw:
            if not isinstance(entry, MappingType):
                continue
            action = str(entry.get("action") or "").strip()
            if not action:
                continue
            target = str(entry.get("target") or "").strip()
            after_json = _coerce_dict(entry.get("after"))
            rationale = str(entry.get("rationale") or "").strip()
            object_type = _infer_object_type(action, entry)
            before_json = _extract_before_payload(
                baseline_json,
                object_type=object_type,
                action=action,
                target=target,
                item=entry,
                after_json=after_json,
            )
            change_set.items.append(
                ChangeItem(
                    object_type=object_type,
                    object_id=0,
                    action=action,
                    target=target,
                    before_json=before_json,
                    after_json=after_json,
                    rationale=rationale or None,
                )
            )
            sanitized_changes.append(
                {
                    "action": action,
                    "target": target,
                    "after": after_json,
                    "rationale": rationale,
                    "object_type": object_type,
                }
            )
            change_count += 1

        session.flush()

        dictionary_updates = [
            dict(update) if isinstance(update, MappingType) else update
            for update in dictionary_updates_raw
        ]

        diff_payload = {
            "proposed_changes": sanitized_changes,
            "dictionary_updates": dictionary_updates,
        }

        return jsonify(
            {
                "ok": True,
                "changeset_id": change_set.id,
                "count": change_count,
                "diff": diff_payload,
            }
        )


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
                select(MappingTable)
                .join(Entity)
                .where(Entity.domain_id == domain.id)
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

