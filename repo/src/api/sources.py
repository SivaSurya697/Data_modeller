"""REST and UI endpoints for managing source metadata."""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, render_template, request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import SourceColumn, SourceSystem, SourceTable
from src.services.source_registry import SourceRegistryService
from src.services.validators import SourceImportRequest, SourceProfileRequest

bp = Blueprint("sources_api", __name__)
ui_bp = Blueprint("sources", __name__, url_prefix="/sources")

_service = SourceRegistryService()


def _serialize_column(column: SourceColumn) -> dict[str, object]:
    return {
        "id": column.id,
        "name": column.name,
        "data_type": column.data_type,
        "is_nullable": column.is_nullable,
        "ordinal_position": column.ordinal_position,
        "description": column.description,
        "statistics": column.statistics or {},
        "sample_values": column.sample_values or [],
    }


def _serialize_table(table: SourceTable) -> dict[str, object]:
    return {
        "id": table.id,
        "system_id": table.system_id,
        "schema_name": table.schema_name,
        "table_name": table.table_name,
        "display_name": table.display_name,
        "description": table.description,
        "schema_definition": table.schema_definition or {},
        "table_statistics": table.table_statistics or {},
        "row_count": table.row_count,
        "sampled_row_count": table.sampled_row_count,
        "profiled_at": table.profiled_at.isoformat() if table.profiled_at else None,
        "columns": [_serialize_column(column) for column in table.columns],
    }


def _serialize_system(system: SourceSystem) -> dict[str, object]:
    return {
        "id": system.id,
        "name": system.name,
        "description": system.description,
        "connection_type": system.connection_type,
        "connection_config": system.connection_config or {},
        "last_imported_at": system.last_imported_at.isoformat()
        if system.last_imported_at
        else None,
        "tables": [_serialize_table(table) for table in system.tables],
    }


@bp.route("/", methods=["GET"])
def list_sources():
    """Return a JSON payload containing registered source systems."""

    with get_db() as session:
        systems = _service.list_systems(session)
    return jsonify([_serialize_system(system) for system in systems])


@bp.route("/import", methods=["POST"])
def import_sources():
    """Persist metadata for a source system and its tables."""

    payload = request.get_json(silent=True)
    if payload is None and request.form:
        raw_payload = request.form.get("payload")
        if raw_payload:
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive branch
                return jsonify({"error": f"Invalid JSON payload: {exc}"}), 400

    if payload is None:
        raw_body = request.data.decode().strip()
        if raw_body:
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError:
                return jsonify({"error": "Request body must be JSON."}), 400
        else:
            return jsonify({"error": "Request body must be JSON."}), 400

    try:
        request_model = SourceImportRequest(**payload)
    except ValidationError as exc:
        return jsonify({"error": exc.errors()}), 400

    with get_db() as session:
        try:
            system = _service.import_source(
                session,
                request_model.model_dump(by_alias=True, exclude_none=True),
            )
            stmt = (
                select(SourceSystem)
                .options(
                    joinedload(SourceSystem.tables).joinedload(SourceTable.columns)
                )
                .where(SourceSystem.id == system.id)
            )
            persisted = session.execute(stmt).unique().scalar_one()
        except ValueError as exc:
            session.rollback()
            return jsonify({"error": str(exc)}), 400

    return jsonify(_serialize_system(persisted)), 201


@bp.route("/profile", methods=["POST"])
def profile_table():
    """Update profiling statistics for a previously imported table."""

    payload = request.get_json(silent=True)
    if payload is None and request.form:
        payload = request.form.to_dict()

    if payload is None and request.data:
        raw_body = request.data.decode().strip()
        if raw_body:
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError:
                return jsonify({"error": "Request body must be JSON."}), 400

    if payload is None:
        return jsonify({"error": "Request body must be JSON."}), 400

    if "table_id" in payload:
        try:
            payload["table_id"] = int(payload["table_id"])
        except (TypeError, ValueError):
            return jsonify({"error": "table_id must be an integer"}), 400

    if isinstance(payload.get("samples"), str):
        try:
            payload["samples"] = json.loads(payload["samples"])
        except json.JSONDecodeError:
            return jsonify({"error": "samples must be valid JSON"}), 400

    if isinstance(payload.get("total_rows"), str) and payload["total_rows"] != "":
        try:
            payload["total_rows"] = int(payload["total_rows"])
        except ValueError:
            return jsonify({"error": "total_rows must be an integer"}), 400

    try:
        request_model = SourceProfileRequest(**payload)
    except ValidationError as exc:
        if not payload.get("samples"):
            table_id = payload.get("table_id")
            if table_id is None:
                return jsonify({"error": exc.errors()}), 400

            with get_db() as session:
                stmt = (
                    select(SourceTable)
                    .options(joinedload(SourceTable.columns))
                    .where(SourceTable.id == table_id)
                )
                result = session.execute(stmt).unique().scalar_one_or_none()
                if result is None:
                    return jsonify({"error": f"Source table {table_id} was not found"}), 404
            return jsonify(_serialize_table(result)), 200

        return jsonify({"error": exc.errors()}), 400

    with get_db() as session:
        try:
            table = _service.profile_table(
                session,
                table_id=request_model.table_id,
                samples=request_model.samples,
                total_rows=request_model.total_rows,
            )
            stmt = (
                select(SourceTable)
                .options(joinedload(SourceTable.columns))
                .where(SourceTable.id == table.id)
            )
            persisted = session.execute(stmt).unique().scalar_one()
        except LookupError as exc:
            session.rollback()
            return jsonify({"error": str(exc)}), 404

    return jsonify(_serialize_table(persisted)), 200


@ui_bp.route("/")
def index():
    """Render the sources dashboard."""

    with get_db() as session:
        systems = _service.list_systems(session)
    return render_template("sources.html", sources=systems)


__all__ = ["bp", "ui_bp"]
