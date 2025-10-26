"""Endpoints supporting draft generation and review."""

from __future__ import annotations

import json
from typing import Any, Mapping

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

from src.models.db import get_db
from src.models.tables import (
    Attribute,
    ChangeItem,
    ChangeSet,
    Domain,
    Entity,
    Relationship,
)
from src.services import diff_helpers
from src.services.llm_modeler import DraftResult, ModelingService, draft_extend
from src.services.model_analysis import classify_entity, extract_relationship_cardinality
from src.services.model_store import load_latest_model_json
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


def _infer_object_type(action: str, item: Mapping[str, Any]) -> str:
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
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return {}


def _extract_before_payload(
    baseline_json: str,
    *,
    object_type: str,
    action: str,
    target: str,
    item: Mapping[str, Any],
    after_json: Mapping[str, Any] | None,
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
    if not isinstance(payload_raw, Mapping):
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

        if not isinstance(diff_payload_raw, Mapping):
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
            if not isinstance(entry, Mapping):
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
            dict(update) if isinstance(update, Mapping) else update
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

