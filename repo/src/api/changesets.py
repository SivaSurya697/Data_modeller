"""Changeset endpoints."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import session_scope
from src.models.tables import ChangeSet, Domain
from src.services.validators import ChangeSetInput

bp = Blueprint("changesets", __name__, url_prefix="/changesets")


def _load_domains() -> list[Domain]:
    with session_scope() as session:
        domains = list(
            session.execute(select(Domain).order_by(Domain.name)).scalars()
        )
    return domains


@bp.route("/", methods=["GET"])
def index() -> str:
    """List changesets and provide creation form."""

    domains = _load_domains()
    with session_scope() as session:
        changesets = list(
            session.execute(
                select(ChangeSet)
                .options(joinedload(ChangeSet.domain))
                .order_by(ChangeSet.created_at.desc())
            ).scalars()
        )
    return render_template(
        "changesets.html", domains=domains, changesets=changesets
    )


@bp.route("/", methods=["POST"])
def create() -> str:
    """Store a new changeset entry."""

    try:
        payload = ChangeSetInput(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("changesets.index"))

    with session_scope() as session:
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
        flash("Changeset recorded.", "success")
    return redirect(url_for("changesets.index"))
