"""Endpoints for managing user settings."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError

from src.models.db import get_db
from src.services.settings import DEFAULT_USER_ID, get_user_settings, save_user_settings
from src.services.validators import UserSettingsInput

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET", "POST"])
def index():
    """Display and update stored user settings."""

    if request.method == "POST":
        try:
            payload = UserSettingsInput(**request.form)
        except ValidationError as exc:
            flash(f"Invalid input: {exc}", "error")
            return redirect(url_for("settings.index"))

        with get_db() as session:
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

    stored = None
    with get_db() as session:
        try:
            stored = get_user_settings(session, DEFAULT_USER_ID)
        except RuntimeError:
            stored = None
    return render_template("settings.html", settings=stored)

