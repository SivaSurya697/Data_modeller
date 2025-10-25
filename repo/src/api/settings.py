"""REST API endpoints for managing user settings."""
from __future__ import annotations

from http import HTTPStatus

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from src.models.db import session_scope
from src.services.settings import (
    DEFAULT_USER_ID,
    get_user_settings,
    save_user_settings,
    UserSettings,
)
from src.services.validators import UserSettingsInput

bp = Blueprint("settings", __name__, url_prefix="/api/settings")


@bp.route("/", methods=["GET"])
def list_settings():
    """Return stored user settings without revealing sensitive values."""

    stored: UserSettings | None = None
    with session_scope() as session:
        try:
            stored = get_user_settings(session, DEFAULT_USER_ID)
        except RuntimeError:
            stored = None
    return render_template("settings.html", settings=stored)


@bp.route("/", methods=["POST"])
def update_settings():
    """Persist user settings supplied as JSON."""

    payload = request.get_json(silent=True) or {}
    try:
        payload = UserSettingsInput(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("settings.index"))

    with session_scope() as session:
        try:
            save_user_settings(
                session,
                DEFAULT_USER_ID,
                openai_api_key=payload.openai_api_key,
                openai_base_url=payload.openai_base_url,
                rate_limit_per_minute=payload.rate_limit_per_minute,
            )
        except RuntimeError as exc:
            flash(f"Could not save settings: {exc}", "error")
            return redirect(url_for("settings.index"))

    flash("Settings stored.", "success")

    return redirect(url_for("settings.index"))
