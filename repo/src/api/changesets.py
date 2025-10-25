"""HTML endpoints for capturing change sets."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import ChangeSet, Domain
from src.services.validators import ChangeSetInput

bp = Blueprint("changesets", __name__, url_prefix="/changesets")


def _load_domains() -> list[Domain]:
    with get_db() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())
    return domains


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

