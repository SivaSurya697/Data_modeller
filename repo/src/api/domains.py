"""Domain management endpoints."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import Domain
from src.services.validators import DomainInput

bp = Blueprint("domains", __name__, url_prefix="/domains")


@bp.route("/", methods=["GET"])
def index() -> str:
    """Display domains and their models."""

    with get_db() as session:
        domains = list(
            session.execute(
                select(Domain)
                .options(joinedload(Domain.entities).joinedload(Entity.attributes))
                .order_by(Domain.name)
            ).scalars()
        )
    return render_template("domains.html", domains=domains)


@bp.route("/", methods=["POST"])
def create() -> str:
    """Create a new domain."""

    try:
        payload = DomainInput(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("domains.index"))

    name = payload.name.strip()
    description = payload.description.strip()

    with get_db() as session:
        existing = session.execute(
            select(Domain).where(Domain.name == name)
        ).scalar_one_or_none()
        if existing:
            flash("Domain already exists.", "error")
            return redirect(url_for("domains.index"))
        domain = Domain(name=name, description=description)
        session.add(domain)
        flash("Domain created.", "success")
    return redirect(url_for("domains.index"))
