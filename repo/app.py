"""Application entry point."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from src.api import changesets, domains, exports, model, settings
from src.models.db import create_all, init_engine
from src.services.settings import load_settings


def create_app() -> Flask:
    """Application factory."""

    load_dotenv()
    instance_path = Path.cwd() / "instance"
    instance_path.mkdir(parents=True, exist_ok=True)
    app = Flask(
        __name__,
        instance_path=str(instance_path),
        instance_relative_config=True,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me")

    config = load_settings()
    app.config["APP_SETTINGS"] = config

    init_engine(config.database_url)
    create_all()

    outputs_dir = Path(__file__).resolve().parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    app.config["ARTIFACTS_DIR"] = str(outputs_dir)

    rate_limit = f"{config.rate_limit_per_minute}/minute"
    Limiter(
        key_func=get_remote_address,
        default_limits=[rate_limit],
        app=app,
    )

    register_blueprints(app)

    @app.route("/")
    def home() -> str:
        return redirect(url_for("settings.index"))

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Initialise database tables."""

        create_all()
        print("Database initialised")

    return app


def register_blueprints(app: Flask) -> None:
    """Register application blueprints."""

    app.register_blueprint(settings.bp)
    app.register_blueprint(domains.bp)
    app.register_blueprint(model.bp)
    app.register_blueprint(changesets.bp)
    app.register_blueprint(exports.bp)


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
