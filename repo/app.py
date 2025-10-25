"""Application entry point."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.api import (
    coverage,
    changesets,
    domains,
    exports,
    model,
    quality,
    relationships,
    settings,
)
from src.api.sources import bp as sources_bp
from src.models.db import create_all, init_engine, load_database_url, session_scope
from src.models.tables import SourceTable
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

    init_engine(load_database_url())
    create_all()

    outputs_dir = Path(__file__).resolve().parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    app.config["ARTIFACTS_DIR"] = str(outputs_dir)

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
        return redirect(url_for("domains.index"))

    @app.get("/sources")
    @app.get("/sources/")
    def list_sources() -> str:
        """Render the sources dashboard with a lightweight view model."""

        with session_scope() as session:
            stmt = (
                select(SourceTable)
                .options(
                    joinedload(SourceTable.system),
                    joinedload(SourceTable.columns),
                )
                .order_by(
                    SourceTable.system_id, SourceTable.schema_name, SourceTable.table_name
                )
            )
            tables = session.execute(stmt).unique().scalars().all()

        systems: dict[int | None, dict[str, object]] = {}
        for table in tables:
            system = table.system
            system_id = system.id if system else None
            if system_id not in systems:
                systems[system_id] = {
                    "id": system.id if system else None,
                    "name": system.name if system else "Unknown system",
                    "description": (system.description or "") if system else "",
                    "connection_type": system.connection_type if system else "unknown",
                    "last_imported_at": (
                        system.last_imported_at.isoformat()
                        if system and system.last_imported_at
                        else None
                    ),
                    "tables": [],
                }

            systems[system_id]["tables"].append(
                {
                    "id": table.id,
                    "schema_name": table.schema_name,
                    "table_name": table.table_name,
                    "display_name": table.display_name or "",
                    "description": table.description or "",
                    "schema_definition": table.schema_definition or {},
                    "table_statistics": table.table_statistics or {},
                    "row_count": table.row_count,
                    "sampled_row_count": table.sampled_row_count,
                    "profiled_at": table.profiled_at.isoformat() if table.profiled_at else None,
                    "columns": [
                        {
                            "id": column.id,
                            "name": column.name,
                            "data_type": column.data_type or "",
                            "is_nullable": column.is_nullable,
                            "description": column.description or "",
                            "statistics": column.statistics or {},
                            "sample_values": column.sample_values or [],
                        }
                        for column in table.columns
                    ],
                }
            )

        vm = list(systems.values())
        return render_template("sources.html", sources=vm)

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
    app.register_blueprint(relationships.bp)
    app.register_blueprint(changesets.bp)
    app.register_blueprint(coverage.bp)
    app.register_blueprint(quality.bp)
    app.register_blueprint(exports.bp)
    app.register_blueprint(sources_bp, url_prefix="/api/sources")


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
