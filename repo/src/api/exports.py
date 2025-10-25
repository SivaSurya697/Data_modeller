"""Model export endpoints."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, flash, redirect, render_template, request, send_from_directory, url_for
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import session_scope
from src.models.tables import DataModel, ExportRecord
from src.services.exporters.dictionary import export_dictionary
from src.services.exporters.plantuml import export_plantuml
from src.services.validators import ExportRequest

bp = Blueprint("exports", __name__, url_prefix="/exports")

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "outputs"
_EXPORTERS = {
    "dictionary": export_dictionary,
    "plantuml": export_plantuml,
}


def _load_models() -> list[DataModel]:
    with session_scope() as session:
        models = list(
            session.execute(
                select(DataModel).options(joinedload(DataModel.domain)).order_by(DataModel.name)
            ).scalars()
        )
    return models


@bp.route("/", methods=["GET"])
def index() -> str:
    """List exports and available models."""

    models = _load_models()
    with session_scope() as session:
        exports = list(
            session.execute(
                select(ExportRecord)
                .options(joinedload(ExportRecord.model).joinedload(DataModel.domain))
                .order_by(ExportRecord.created_at.desc())
            ).scalars()
        )
    return render_template("exports.html", models=models, exports=exports)


@bp.route("/", methods=["POST"])
def create() -> str:
    """Generate a new export file."""

    try:
        payload = ExportRequest(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("exports.index"))

    exporter = _EXPORTERS[payload.exporter]

    with session_scope() as session:
        model = session.execute(
            select(DataModel)
            .options(joinedload(DataModel.domain))
            .where(DataModel.id == payload.model_id)
        ).scalar_one_or_none()
        if model is None:
            flash("Model not found.", "error")
            return redirect(url_for("exports.index"))

        file_path = exporter(model, _OUTPUT_DIR)
        record = ExportRecord(model=model, exporter=payload.exporter, file_path=str(file_path))
        session.add(record)
        flash("Export generated.", "success")

    return redirect(url_for("exports.index"))


@bp.route("/<int:export_id>/download", methods=["GET"])
def download(export_id: int) -> Response:
    """Download a generated export."""

    with session_scope() as session:
        record = session.get(ExportRecord, export_id)
        if record is None:
            flash("Export not found.", "error")
            return redirect(url_for("exports.index"))
        path = Path(record.file_path)
        if not path.exists():
            flash("Export file missing from disk.", "error")
            return redirect(url_for("exports.index"))
    return send_from_directory(path.parent, path.name, as_attachment=True)
