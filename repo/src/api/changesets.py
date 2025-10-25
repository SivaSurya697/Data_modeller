"""API endpoints for working with change sets."""
from __future__ import annotations

from http import HTTPStatus

from flask import Blueprint, request
from sqlalchemy import select

from src.models.db import get_db
from src.models.tables import ChangeSet, DataModel
from src.services.validators import ChangeSetInput

    header_candidates = ("X-User", "X-User-Email", "X-User-Id")
    for header in header_candidates:
        value = request.headers.get(header)
        if value:
            return value
    return "system"


def _load_models() -> list[DataModel]:
    with get_db() as session:
        models = list(
            session.execute(
                select(DataModel).options(joinedload(DataModel.domain)).order_by(DataModel.name)
            ).scalars()
        )
    return models


@bp.get("/")
def index() -> tuple[list[dict[str, object]], int]:
    """Return a list of change sets with minimal metadata."""

    models = _load_models()
    with get_db() as session:
        changesets = list(
            session.execute(
                select(ChangeSet).order_by(ChangeSet.created_at.desc())
            ).scalars()
        )
    return render_template(
        "changesets.html", models=models, changesets=changesets
    )


@bp.route("/", methods=["POST"])
def create() -> str:
    """Store a new changeset entry."""

    try:
        payload = ChangeSetInput(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("changesets.index"))

    with get_db() as session:
        model = session.get(DataModel, payload.model_id)
        if model is None:
            flash("Model not found.", "error")
            return redirect(url_for("changesets.index"))
        session.add(ChangeSet(model=model, description=payload.description.strip()))
        flash("Changeset recorded.", "success")
    return redirect(url_for("changesets.index"))
