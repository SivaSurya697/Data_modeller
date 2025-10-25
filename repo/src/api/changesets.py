"""Changeset endpoints."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import ChangeSet, DataModel
from src.services.validators import ChangeSetInput

bp = Blueprint("changesets", __name__, url_prefix="/changesets")


def _load_models() -> list[DataModel]:
    with get_db() as session:
        models = list(
            session.execute(
                select(DataModel).options(joinedload(DataModel.domain)).order_by(DataModel.name)
            ).scalars()
        )
    return models


@bp.route("/", methods=["GET"])
def index() -> str:
    """List changesets and provide creation form."""

    models = _load_models()
    with get_db() as session:
        changesets = list(
            session.execute(
                select(ChangeSet)
                .options(joinedload(ChangeSet.model).joinedload(DataModel.domain))
                .order_by(ChangeSet.created_at.desc())
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
