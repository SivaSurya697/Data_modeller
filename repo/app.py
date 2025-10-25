"""Application entry point."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from src.api import changesets, domains, exports, model, settings
from src.models.db import create_all, init_engine, session_scope
from src.services.settings import DEFAULT_USER_ID, get_user_settings


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

    database_url = os.getenv("DATABASE_URL", "sqlite:///data_modeller.db")
    init_engine(database_url)
    create_all()

    outputs_dir = Path(__file__).resolve().parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    rate_limit_value = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    with session_scope() as session:
        try:
            user_settings = get_user_settings(session, DEFAULT_USER_ID)
            rate_limit_value = user_settings.rate_limit_per_minute
        except RuntimeError:
            pass
        except Exception as exc:  # pragma: no cover - defensive logging path
            app.logger.warning("Failed to load user settings: %s", exc)
    rate_limit = f"{rate_limit_value}/minute"
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
