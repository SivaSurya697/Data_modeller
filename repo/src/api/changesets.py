"""Endpoints for capturing change sets and exposing API detail views."""

from __future__ import annotations

from typing import Any

from flask import (
    Blueprint,
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

