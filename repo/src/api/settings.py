"""REST API endpoints for managing user settings."""
from __future__ import annotations

from http import HTTPStatus

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from src.services.user_settings import get_user_settings, save_user_settings
from src.services.validators import UserSettingsPayload

bp = Blueprint("settings", __name__, url_prefix="/api/settings")


@bp.route("/", methods=["GET"])
def list_settings():
    """Return stored user settings without revealing sensitive values."""

    settings = get_user_settings(include_api_key=False)
    return jsonify({"settings": settings}), HTTPStatus.OK


@bp.route("/", methods=["POST"])
def update_settings():
    """Persist user settings supplied as JSON."""

    payload = request.get_json(silent=True) or {}
    try:
        data = UserSettingsPayload(**payload)
    except ValidationError as exc:
        return (
            jsonify({"error": "Invalid settings payload", "details": exc.errors()}),
            HTTPStatus.BAD_REQUEST,
        )

    save_user_settings(
        openai_api_key=data.openai_api_key,
        openai_base_url=data.openai_base_url,
    )

    settings = get_user_settings(include_api_key=False)
    return (
        jsonify({"message": "Settings updated", "settings": settings}),
        HTTPStatus.OK,
    )
