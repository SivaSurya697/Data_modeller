"""Settings blueprint."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select

from src.models.db import session_scope
from src.models.tables import Setting
from src.services.settings import load_settings
from src.services.validators import SettingInput

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET"])
def index() -> str:
    """Render the settings dashboard."""

    config = load_settings()
    with session_scope() as session:
        settings = list(
            session.execute(select(Setting).order_by(Setting.key)).scalars()
        )
    return render_template("settings.html", config=config, settings=settings)


@bp.route("/", methods=["POST"])
def persist() -> str:
    """Persist a configuration override."""

    try:
        payload = SettingInput(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("settings.index"))

    key = payload.key.strip()
    value = payload.value.strip()

    with session_scope() as session:
        existing = session.execute(
            select(Setting).where(Setting.key == key)
        ).scalar_one_or_none()
        if existing:
            existing.key = key
            existing.value = value
            flash("Setting updated.", "success")
        else:
            session.add(Setting(key=key, value=value))
            flash("Setting stored.", "success")

    return redirect(url_for("settings.index"))
