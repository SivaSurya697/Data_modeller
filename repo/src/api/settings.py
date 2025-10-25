"""Settings blueprint."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select

from src.models.db import session_scope
from src.models.tables import Setting
from src.services.settings import load_settings
from src.services.validators import SettingsInput

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET"])
def index() -> str:
    """Render the settings dashboard."""

    config = load_settings()
    with session_scope() as session:
        current = session.execute(
            select(Setting).order_by(Setting.updated_at.desc())
        ).scalar_one_or_none()
    return render_template("settings.html", config=config, setting=current)


@bp.route("/", methods=["POST"])
def persist() -> str:
    """Persist a configuration override."""

    try:
        payload = SettingsInput(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("settings.index"))

    with session_scope() as session:
        current = session.execute(select(Setting).limit(1)).scalar_one_or_none()
        if current is None:
            current = Setting()
            session.add(current)
        current.api_key_enc = (payload.api_key or "").strip() or None
        current.base_url = (payload.base_url or "").strip() or None
        current.model_name = (payload.model_name or "").strip() or None
        flash("Settings saved.", "success")

    return redirect(url_for("settings.index"))
