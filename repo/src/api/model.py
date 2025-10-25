"""Model drafting endpoints."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select

from src.models.db import session_scope
from src.models.tables import Domain
from src.services.llm_modeler import ModelingService
from src.services.settings import load_settings
from src.services.validators import DraftRequest

bp = Blueprint("modeler", __name__, url_prefix="/modeler")


def _load_domains() -> list[Domain]:
    with session_scope() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())
    return domains


@bp.route("/", methods=["GET"])
def draft_review() -> str:
    """Render the draft review screen."""

    domains = _load_domains()
    return render_template("draft_review.html", domains=domains, draft=None)


@bp.route("/", methods=["POST"])
def generate_draft() -> str:
    """Generate a model draft using the LLM."""

    try:
        payload = DraftRequest(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("modeler.draft_review"))

    settings = load_settings()
    service = ModelingService(settings)

    try:
        with session_scope() as session:
            result = service.generate_draft(session, payload)
            draft = {
                "entities": result.entities,
                "impact": result.impact,
            }
    except Exception as exc:
        flash(f"Draft generation failed: {exc}", "error")
        return redirect(url_for("modeler.draft_review"))

    flash("Draft generated successfully.", "success")
    domains = _load_domains()
    return render_template("draft_review.html", domains=domains, draft=draft)
