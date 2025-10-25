from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any, Mapping

from flask import Blueprint, Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from src.models.db import get_db
from src.models.tables import DataModel, ExportRecord
from src.services.exporters.dictionary import emit_dictionary_md
from src.services.exporters.plantuml import export_plantuml
from src.services.form_validators import ExportRequest

bp = Blueprint("exports_api", __name__, url_prefix="/api/exports")


@bp.post("/plantuml")
def create_plantuml() -> tuple[Response, int]:
    """Generate a PlantUML diagram from the provided model payload."""

def _load_models() -> list[DataModel]:
    with get_db() as session:
        models = list(
            session.execute(
                select(Domain)
                .options(joinedload(Domain.entities).joinedload(Entity.attributes))
                .order_by(Domain.name)
            ).scalars()
        )
    return domains


@bp.route("/", methods=["GET"])
def index() -> str:
    """List exports and available domains."""

    models = _load_models()
    with get_db() as session:
        exports = list(
            session.execute(
                select(ExportRecord)
                .options(joinedload(ExportRecord.domain))
                .order_by(ExportRecord.created_at.desc())
            ).scalars()
        )
    return render_template("exports.html", domains=domains, exports=exports)

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
        if domain is None:
            flash("Domain not found.", "error")
            return redirect(url_for("exports.index"))

        file_path = exporter(domain, _OUTPUT_DIR)
        record = ExportRecord(domain=domain, exporter=payload.exporter, file_path=str(file_path))
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
