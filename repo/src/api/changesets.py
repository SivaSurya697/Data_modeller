"""Endpoints for capturing change sets and exposing API detail views."""

from __future__ import annotations

from typing import Any

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    flash,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from src.models.db import get_db
from src.models.tables import ChangeItem, ChangeSet, Domain
from src.services.model_store import load_latest_model_json
from src.services import model_merge
from src.services.validators import ChangeSetInput

bp = Blueprint("changesets", __name__, url_prefix="/changesets")
api_bp = Blueprint("changesets_api", __name__, url_prefix="/api/changesets")


def _load_domains() -> list[Domain]:
    with get_db() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())
    return domains


_ALLOWED_STATE_UPDATES = {"draft", "in_review", "approved"}
_STATE_TRANSITIONS = {
    "draft": {"draft", "in_review"},
    "in_review": {"draft", "in_review", "approved"},
    "approved": {"approved"},
    "published": set(),
}


def _serialise_change_item(item: ChangeItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "object_type": item.object_type,
        "action": item.action,
        "target": item.target,
        "before_json": item.before_json,
        "after_json": item.after_json,
        "rationale": item.rationale or "",
    }


def _serialise_change_set(change_set: ChangeSet, *, include_items: bool = False) -> dict[str, Any]:
    data = {
        "id": change_set.id,
        "title": change_set.title,
        "state": change_set.state,
        "domain": change_set.domain.name if change_set.domain else None,
        "created_at": change_set.created_at.isoformat(),
    }
    if include_items:
        data["items"] = [_serialise_change_item(item) for item in change_set.items]
    return data


def infer_target_from_changeitem(item: ChangeItem) -> str:
    """Infer the merge target string for a ``ChangeItem``."""

    target = str(item.target or "").strip()
    after = item.after_json if isinstance(item.after_json, dict) else {}
    before = item.before_json if isinstance(item.before_json, dict) else {}

    if item.object_type == "relationship":
        def _pick(source: dict[str, Any], *keys: str) -> str:
            for key in keys:
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        from_name = _pick(after, "from", "from_name", "source", "from_entity") if after else ""
        to_name = _pick(after, "to", "to_name", "target", "target_entity", "to_entity") if after else ""
        if not from_name and before:
            from_name = _pick(before, "from", "from_name", "source", "from_entity")
        if not to_name and before:
            to_name = _pick(before, "to", "to_name", "target", "target_entity", "to_entity")
        if (not from_name or not to_name) and "->" in target:
            left, right = (part.strip() for part in target.split("->", 1))
            from_name = from_name or left
            to_name = to_name or right
        if from_name and to_name:
            return f"{from_name}->{to_name}"
        return target

    if item.object_type == "entity":
        name = after.get("name") if after else None
        if not name:
            name = before.get("name") if before else None
        if isinstance(name, str) and name.strip():
            return name.strip()
        return target or (item.rationale or "").strip()

    if item.object_type == "dictionary_update":
        term = after.get("term") if after else None
        if not term and before:
            term = before.get("term")
        if isinstance(term, str) and term.strip():
            return term.strip()

    return target or (item.rationale or "").strip()


def build_merge_payload(items: list[ChangeItem]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(proposed_changes, dictionary_updates)`` for ``items``."""

    proposed_changes: list[dict[str, Any]] = []
    dictionary_updates: list[dict[str, Any]] = []

    for item in items:
        after = item.after_json if isinstance(item.after_json, dict) else {}
        rationale = str(item.rationale or "").strip()
        if item.object_type == "dictionary_update":
            if after:
                dictionary_updates.append(dict(after))
            continue
        target = infer_target_from_changeitem(item)
        proposed_changes.append(
            {
                "action": item.action,
                "target": target,
                "after": dict(after),
                "rationale": rationale,
            }
        )

    return proposed_changes, dictionary_updates


def _collect_merge_inputs(
    change_set_id: int, domain_name: str
) -> tuple[
    str | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
    tuple[dict[str, Any], int] | None,
]:
    domain = domain_name.strip()
    if not domain:
        return None, [], [], ({"ok": False, "error": "Domain name is required."}, 400)

    artifacts_dir = current_app.config.get("ARTIFACTS_DIR", "outputs")
    baseline_json = load_latest_model_json(artifacts_dir, domain)
    if baseline_json is None:
        return (
            None,
            [],
            [],
            ({"ok": False, "error": "No published model found for domain."}, 404),
        )

    with get_db() as session:
        change_set = (
            session.execute(
                select(ChangeSet)
                .options(joinedload(ChangeSet.domain))
                .options(selectinload(ChangeSet.items))
                .where(ChangeSet.id == change_set_id)
            )
            .unique()
            .scalar_one_or_none()
        )

        if change_set is None:
            return None, [], [], ({"ok": False, "error": "ChangeSet not found."}, 404)

        if not change_set.domain or change_set.domain.name != domain:
            return (
                None,
                [],
                [],
                (
                    {
                        "ok": False,
                        "error": "ChangeSet does not belong to the specified domain.",
                    },
                    400,
                ),
            )

        proposed_changes, dictionary_updates = build_merge_payload(list(change_set.items))

    return baseline_json, proposed_changes, dictionary_updates, None


@api_bp.get("/")
def list_changesets() -> Any:
    with get_db() as session:
        records = (
            session.execute(
                select(ChangeSet)
                .options(joinedload(ChangeSet.domain))
                .order_by(ChangeSet.created_at.desc())
            )
            .scalars()
            .all()
        )
    payload = [_serialise_change_set(record) for record in records]
    return jsonify(payload)


@api_bp.get("/<int:change_set_id>")
def get_changeset(change_set_id: int) -> Any:
    with get_db() as session:
        change_set = (
            session.execute(
                select(ChangeSet)
                .options(joinedload(ChangeSet.domain))
                .options(selectinload(ChangeSet.items))
                .where(ChangeSet.id == change_set_id)
            )
            .unique()
            .scalar_one_or_none()
        )
    if change_set is None:
        if request.accept_mimetypes.accept_html and not request.accept_mimetypes.accept_json:
            return ("<p>Change set not found.</p>", 404)
        return jsonify({"ok": False, "error": "ChangeSet not found."}), 404

    prefers_html = (
        request.accept_mimetypes.accept_html
        and (
            not request.accept_mimetypes.accept_json
            or request.accept_mimetypes["text/html"]
            >= request.accept_mimetypes["application/json"]
        )
    )
    if prefers_html:
        return render_template("components/changeset_detail.html", change_set=change_set)

    return jsonify(_serialise_change_set(change_set, include_items=True))


def _extract_domain_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict()
    return payload


@api_bp.post("/<int:change_set_id>/dryrun")
def dryrun_changeset(change_set_id: int) -> Any:
    payload = _extract_domain_payload()
    domain_name = str(payload.get("domain") or "").strip()

    baseline_json, proposed_changes, dictionary_updates, error = _collect_merge_inputs(
        change_set_id, domain_name
    )
    if error:
        body, status_code = error
        response = jsonify(body)
        response.status_code = status_code
        return response

    result = model_merge.apply_changes(
        baseline_json,
        proposed_changes,
        dictionary_updates if dictionary_updates else None,
    )
    return jsonify(result)


@api_bp.post("/<int:change_set_id>/apply")
def apply_changeset(change_set_id: int) -> Any:
    payload = _extract_domain_payload()
    domain_name = str(payload.get("domain") or "").strip()

    baseline_json, proposed_changes, dictionary_updates, error = _collect_merge_inputs(
        change_set_id, domain_name
    )
    if error:
        body, status_code = error
        response = jsonify(body)
        response.status_code = status_code
        return response

    result = model_merge.apply_changes(
        baseline_json,
        proposed_changes,
        dictionary_updates if dictionary_updates else None,
    )

    if not result.get("ok", False):
        response = jsonify(result)
        response.status_code = 400
        return response

    return jsonify(
        {
            "ok": True,
            "message": "ready for publish",
            "applied": result.get("applied", []),
            "model_json": result.get("model_json"),
        }
    )


@api_bp.post("/<int:change_set_id>/state")
def update_changeset_state(change_set_id: int) -> Any:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict()

    new_state = str(payload.get("state") or "").strip()
    if new_state not in _ALLOWED_STATE_UPDATES:
        return jsonify({"ok": False, "error": "Invalid state requested."}), 400

    with get_db() as session:
        change_set = (
            session.execute(
                select(ChangeSet)
                .options(joinedload(ChangeSet.domain))
                .options(selectinload(ChangeSet.items))
                .where(ChangeSet.id == change_set_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if change_set is None:
            return jsonify({"ok": False, "error": "ChangeSet not found."}), 404

        allowed_targets = _STATE_TRANSITIONS.get(change_set.state, {change_set.state})
        if new_state not in allowed_targets:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": f"Cannot move change set from {change_set.state} to {new_state}.",
                    }
                ),
                400,
            )

        change_set.state = new_state
        session.flush()

    prefers_html = (
        request.accept_mimetypes.accept_html
        and (
            not request.accept_mimetypes.accept_json
            or request.accept_mimetypes["text/html"]
            >= request.accept_mimetypes["application/json"]
        )
    )
    if prefers_html:
        return render_template("components/changeset_detail.html", change_set=change_set)

    return jsonify({"ok": True, "state": new_state})


@bp.route("/", methods=["GET", "POST"])
def index():
    """Render the change set list and creation form."""

    if request.method == "POST":
        try:
            payload = ChangeSetInput(**request.form)
        except ValidationError as exc:
            flash(f"Invalid input: {exc}", "error")
            return redirect(url_for("changesets.index"))

        with get_db() as session:
            domain = session.get(Domain, payload.domain_id)
            if domain is None:
                flash("Domain not found.", "error")
                return redirect(url_for("changesets.index"))
            session.add(
                ChangeSet(
                    domain=domain,
                    title=payload.title.strip(),
                    summary=payload.summary.strip(),
                    created_by=1,
                    state="draft",
                )
            )
            flash("Change set recorded.", "success")
        return redirect(url_for("changesets.index"))

    domains = _load_domains()
    with get_db() as session:
        changesets = list(
            session.execute(
                select(ChangeSet)
                .options(joinedload(ChangeSet.domain))
                .order_by(ChangeSet.created_at.desc())
            ).scalars()
        )
    return render_template("changesets.html", domains=domains, changesets=changesets)

