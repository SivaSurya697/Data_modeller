"""Endpoints supporting draft generation and review."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select

from src.models.db import get_db
from src.models.tables import Domain
from src.services.llm_modeler import ModelingService
from src.services.validators import DraftRequest

bp = Blueprint("modeler", __name__, url_prefix="/modeler")


def _load_domains() -> list[Domain]:
    with get_db() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())
    return domains


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
                draft = {
                    "entities": result.entities,
                    "impact": result.impact,
                }
            flash("Draft generated successfully.", "success")
        except Exception as exc:  # pragma: no cover - surface to UI
            flash(f"Draft generation failed: {exc}", "error")
            return redirect(url_for("modeler.draft_review"))

    domains = _load_domains()
    return render_template("draft_review.html", domains=domains, draft=draft)

