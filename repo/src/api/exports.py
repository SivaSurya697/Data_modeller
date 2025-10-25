"""Endpoints for managing export generation."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import Domain, Entity, ExportRecord
from src.services.exporters.dictionary import export_dictionary
from src.services.exporters.plantuml import export_plantuml
from src.services.validators import ExportRequest

bp = Blueprint("exports", __name__, url_prefix="/exports")

_EXPORTERS = {
    "dictionary": export_dictionary,
    "plantuml": export_plantuml,
}


def _load_domains() -> list[Domain]:
    with get_db() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())
    return domains


@bp.route("/", methods=["GET", "POST"])
def index():
    """Render the exports screen and handle new export requests."""

    if request.method == "POST":
        try:
            payload = ExportRequest(**request.form)
        except ValidationError as exc:
            flash(f"Invalid input: {exc}", "error")
            return redirect(url_for("exports.index"))

        exporter = _EXPORTERS[payload.exporter]
        with get_db() as session:
            domain = (
                session.execute(
                    select(Domain)
                    .options(joinedload(Domain.entities).joinedload(Entity.attributes))
                    .where(Domain.id == payload.domain_id)
                )
                .unique()
                .scalar_one_or_none()
            )
            if domain is None:
                flash("Domain not found.", "error")
                return redirect(url_for("exports.index"))

            output_dir = Path(current_app.config.get("ARTIFACTS_DIR", "outputs"))
            file_path = exporter(domain, output_dir)
            session.add(
                ExportRecord(domain=domain, exporter=payload.exporter, file_path=str(file_path))
            )
            flash("Export generated.", "success")
        return redirect(url_for("exports.index"))

    domains = _load_domains()
    with get_db() as session:
        exports = list(
            session.execute(
                select(ExportRecord)
                .options(joinedload(ExportRecord.domain))
                .order_by(ExportRecord.created_at.desc())
            ).scalars()
        )
    return render_template("exports.html", domains=domains, exports=exports)


@bp.route("/<int:export_id>/download")
def download(export_id: int):
    """Download an export file from disk."""

    with get_db() as session:
        record = session.get(ExportRecord, export_id)
        if record is None:
            flash("Export not found.", "error")
            return redirect(url_for("exports.index"))
        path = Path(record.file_path)
        if not path.exists():
            flash("Export file missing from disk.", "error")
            return redirect(url_for("exports.index"))
    return send_from_directory(path.parent, path.name, as_attachment=True)

