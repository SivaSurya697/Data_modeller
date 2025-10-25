"""Model export API endpoints."""
from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any, Mapping

from flask import Blueprint, Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from src.services.exporters.dictionary import emit_dictionary_md
from src.services.exporters.plantuml import emit_plantuml

bp = Blueprint("exports_api", __name__, url_prefix="/api/exports")


@bp.post("/plantuml")
def create_plantuml() -> tuple[Response, int]:
    """Generate a PlantUML diagram from the provided model payload."""

    model_payload = _parse_model_payload()
    artifacts_dir = _artifacts_dir()
    try:
        file_path = emit_plantuml(model_payload, artifacts_dir)
    except ValueError as exc:  # pragma: no cover - defensive path validation
        raise BadRequest(str(exc)) from exc

    return _success_response(file_path, artifacts_dir)


@bp.post("/dictionary")
def create_dictionary() -> tuple[Response, int]:
    """Generate a markdown data dictionary from the provided model payload."""

    model_payload = _parse_model_payload()
    artifacts_dir = _artifacts_dir()
    try:
        file_path = emit_dictionary_md(model_payload, artifacts_dir)
    except ValueError as exc:  # pragma: no cover - defensive path validation
        raise BadRequest(str(exc)) from exc

    return _success_response(file_path, artifacts_dir)


def _parse_model_payload() -> Mapping[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object")

    if "model_json" not in data:
        raise BadRequest("'model_json' field is required")

    raw_model = data["model_json"]
    if isinstance(raw_model, str):
        try:
            model_payload = json.loads(raw_model)
        except json.JSONDecodeError as exc:
            raise BadRequest("'model_json' string must contain valid JSON") from exc
    elif isinstance(raw_model, dict):
        model_payload = raw_model
    else:
        raise BadRequest("'model_json' must be an object or JSON string")

    if not isinstance(model_payload, dict):
        raise BadRequest("'model_json' must decode to a JSON object")

    return model_payload


def _artifacts_dir() -> Path:
    configured = current_app.config.get("ARTIFACTS_DIR")
    if configured:
        return Path(configured)

    fallback = Path(current_app.root_path).parent / "outputs"
    current_app.config["ARTIFACTS_DIR"] = str(fallback)
    return fallback


def _success_response(file_path: Path, artifacts_dir: Path) -> tuple[Response, int]:
    base = artifacts_dir.resolve()
    file_location = file_path.resolve().relative_to(base)
    payload = {"ok": True, "file": str(file_location)}
    return jsonify(payload), HTTPStatus.CREATED
