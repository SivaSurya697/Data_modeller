"""Coverage API exposing MECE analysis."""

from __future__ import annotations

import json
from http import HTTPStatus

from flask import Blueprint, current_app, jsonify, request

from src.services.coverage_analyzer import analyze_mece
from src.services.model_store import load_latest_model_json

bp = Blueprint("coverage", __name__)


@bp.post("/analyze")
def analyze() -> tuple[object, int] | object:
    """Analyze the supplied model or latest published domain model."""

    payload = request.get_json(silent=True) or {}

    model_json = payload.get("model_json")
    domain = payload.get("domain")

    model_json_str: str | None = None
    if model_json is not None:
        if isinstance(model_json, str):
            model_json_str = model_json
        else:
            try:
                model_json_str = json.dumps(model_json)
            except (TypeError, ValueError) as exc:  # pragma: no cover - invalid payload
                return (
                    jsonify({"ok": False, "error": f"model_json is not serializable: {exc}"}),
                    HTTPStatus.BAD_REQUEST,
                )
    elif isinstance(domain, str) and domain.strip():
        artifacts_dir = current_app.config.get("ARTIFACTS_DIR")
        if not artifacts_dir:
            return (
                jsonify({"ok": False, "error": "Artifacts directory is not configured."}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        model_json_str = load_latest_model_json(artifacts_dir, domain.strip())
        if model_json_str is None:
            return (
                jsonify({"ok": False, "error": "No published model found."}),
                HTTPStatus.NOT_FOUND,
            )
    else:
        return (
            jsonify({"ok": False, "error": "Provide either 'model_json' or 'domain'."}),
            HTTPStatus.BAD_REQUEST,
        )

    try:
        analysis = analyze_mece(model_json_str)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), HTTPStatus.BAD_REQUEST

    return jsonify({"ok": True, "analysis": analysis})


__all__ = ["bp"]
