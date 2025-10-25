"""Domain management endpoints."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import Domain, Entity
from src.services.validators import DomainInput

bp = Blueprint("domains", __name__, url_prefix="/domains")


def _load_domains() -> list[Domain]:
    with get_db() as session:
        stmt = (
            select(Domain)
            .options(joinedload(Domain.entities).joinedload(Entity.attributes))
            .order_by(Domain.name)
        )
        domains = list(session.scalars(stmt).unique())
    return domains


@bp.route("/", methods=["GET", "POST"])
def index():
    """List existing domains and handle creation requests."""

    if request.method == "POST":
        submission = request.get_json(silent=True) or request.form.to_dict()
        try:
            payload = DomainInput(**submission)
        except ValidationError as exc:
            messages = ", ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in exc.errors()
            )
            flash(f"Invalid input: {messages}", "error")
            return redirect(url_for("domains.index"))

        name = payload.name.strip()
        description = payload.description.strip()

        with get_db() as session:
            existing = session.execute(
                select(Domain).where(Domain.name.ilike(name))
            ).scalar_one_or_none()
            if existing:
                flash("Domain already exists.", "error")
            else:
                session.add(Domain(name=name, description=description))
                flash("Domain created.", "success")
        return redirect(url_for("domains.index"))

    domains = _load_domains()
    return render_template("domains.html", domains=domains)

