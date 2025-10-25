"""Model export API endpoints."""
from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any, Mapping

from flask import Blueprint, Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from src.models.db import get_db
from src.models.tables import DataModel, ExportRecord
from src.services.exporters.dictionary import export_dictionary
from src.services.exporters.plantuml import export_plantuml
from src.services.validators import ExportRequest

bp = Blueprint("exports_api", __name__, url_prefix="/api/exports")


@bp.post("/plantuml")
def create_plantuml() -> tuple[Response, int]:
    """Generate a PlantUML diagram from the provided model payload."""

def _load_models() -> list[DataModel]:
    with get_db() as session:
        models = list(
            session.execute(
                select(DataModel).options(joinedload(DataModel.domain)).order_by(DataModel.name)
            ).scalars()
        )
    return models


@bp.post("/dictionary")
def create_dictionary() -> tuple[Response, int]:
    """Generate a markdown data dictionary from the provided model payload."""

    models = _load_models()
    with get_db() as session:
        exports = list(
            session.execute(
                select(ExportRecord)
                .options(joinedload(ExportRecord.model).joinedload(DataModel.domain))
                .order_by(ExportRecord.created_at.desc())
            ).scalars()
        )
    return render_template("exports.html", models=models, exports=exports)

    return _success_response(file_path, artifacts_dir)


    try:
        payload = ExportRequest(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("exports.index"))

    exporter = _EXPORTERS[payload.exporter]

    with get_db() as session:
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
