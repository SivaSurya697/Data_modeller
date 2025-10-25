"""REST API for managing imported source metadata."""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, render_template, request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.db import get_db
from src.models.tables import SourceSystem, SourceTable
from src.services.profiler import merge_statistics, summarise_preview

bp = Blueprint("sources_api", __name__)
ui_bp = Blueprint("sources", __name__, url_prefix="/sources")

_DEFAULT_SYSTEM_NAME = "default"
_DEFAULT_CONNECTION_TYPE = "external"
_DEFAULT_SCHEMA = "public"


def _normalise_name(name: str) -> tuple[str, str]:
    """Split a fully qualified table name into schema and table components."""

    parts = [segment.strip() for segment in name.split(".") if segment.strip()]
    if not parts:
        raise ValueError("Source entries must include a non-empty name")
    if len(parts) == 1:
        return _DEFAULT_SCHEMA, parts[0]
    schema = ".".join(parts[:-1])
    return schema, parts[-1]


def _ensure_default_system(session: Session) -> SourceSystem:
    """Return or create the default source system."""

    stmt = select(SourceSystem).where(SourceSystem.name == _DEFAULT_SYSTEM_NAME)
    system = session.execute(stmt).scalar_one_or_none()
    if system is None:
        system = SourceSystem(
            name=_DEFAULT_SYSTEM_NAME,
            connection_type=_DEFAULT_CONNECTION_TYPE,
        )
        session.add(system)
        session.flush()
    return system


def _serialise_table(table: SourceTable) -> dict[str, Any]:
    """Return the public representation of a ``SourceTable``."""

    return {
        "name": f"{table.schema_name}.{table.table_name}",
        "schema": table.schema_definition or {},
        "stats": table.table_statistics or {},
        "row_count": table.row_count,
        "sampled_row_count": table.sampled_row_count,
        "profiled_at": (
            table.profiled_at.astimezone(timezone.utc).isoformat()
            if table.profiled_at
            else None
        ),
        "description": table.description,
        "display_name": table.display_name,
    }


def _find_table_by_name(session: Session, name: str) -> SourceTable | None:
    schema_name, table_name = _normalise_name(name)
    stmt = (
        select(SourceTable)
        .join(SourceSystem)
        .where(SourceSystem.name == _DEFAULT_SYSTEM_NAME)
        .where(SourceTable.schema_name == schema_name)
        .where(SourceTable.table_name == table_name)
    )
    return session.execute(stmt).scalar_one_or_none()


@bp.get("/")
def list_sources():
    """Return all imported sources."""

    with get_db() as session:
        system = _ensure_default_system(session)
        stmt = (
            select(SourceTable)
            .where(SourceTable.system_id == system.id)
            .order_by(SourceTable.schema_name, SourceTable.table_name)
        )
        tables = list(session.execute(stmt).scalars())
    return jsonify({"sources": [_serialise_table(table) for table in tables]})


@bp.get("/<path:source_name>")
def get_source(source_name: str):
    """Return details for a single imported source."""

    try:
        with get_db() as session:
            table = _find_table_by_name(session, source_name)
            if table is None:
                return jsonify({"error": f"Source '{source_name}' was not found."}), 404
            payload = _serialise_table(table)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"source": payload})


@bp.post("/import")
def import_sources():
    """Create or update source metadata in bulk."""

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

    sources = payload.get("sources")
    if not isinstance(sources, list):
        return jsonify({"error": "Import payload must include a 'sources' array."}), 400

    with get_db() as session:
        system = _ensure_default_system(session)
        created = 0
        updated = 0
        serialised: list[dict[str, Any]] = []

        for entry in sources:
            if not isinstance(entry, dict):
                return jsonify({"error": "Each source entry must be an object."}), 400

            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                return jsonify({"error": "Source entries require a non-empty 'name'."}), 400

            try:
                schema_name, table_name = _normalise_name(name)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

            stmt = (
                select(SourceTable)
                .where(SourceTable.system_id == system.id)
                .where(SourceTable.schema_name == schema_name)
                .where(SourceTable.table_name == table_name)
            )
            table = session.execute(stmt).scalar_one_or_none()
            is_new = table is None

            if is_new:
                table = SourceTable(
                    system_id=system.id,
                    schema_name=schema_name,
                    table_name=table_name,
                )
                session.add(table)

            changed = False

            for attr in ("display_name", "description"):
                if attr in entry:
                    value = entry.get(attr)
                    if getattr(table, attr) != value:
                        setattr(table, attr, value)
                        changed = True

            schema_definition = entry.get("schema") or entry.get("schema_definition")
            if schema_definition is not None and table.schema_definition != schema_definition:
                table.schema_definition = schema_definition
                changed = True

            stats = entry.get("stats") or entry.get("statistics")
            if stats is not None:
                if table.table_statistics is None:
                    table.table_statistics = stats
                    changed = True
                else:
                    merged = merge_statistics(table.table_statistics, stats)
                    if merged != table.table_statistics:
                        table.table_statistics = merged
                        changed = True

            if "row_count" in entry:
                row_count = entry.get("row_count")
                if table.row_count != row_count:
                    table.row_count = row_count
                    changed = True

            if "profiled_at" in entry and entry.get("profiled_at"):
                profiled_at = _parse_datetime(entry.get("profiled_at"))
                if profiled_at and table.profiled_at != profiled_at:
                    table.profiled_at = profiled_at
                    changed = True

            if "sampled_row_count" in entry:
                sampled = entry.get("sampled_row_count")
                if table.sampled_row_count != sampled:
                    table.sampled_row_count = sampled
                    changed = True

            if table.table_statistics is not None:
                if table.row_count is None:
                    maybe_row_count = table.table_statistics.get("row_count")
                    if maybe_row_count is not None and table.row_count != maybe_row_count:
                        table.row_count = maybe_row_count
                        changed = True
                if table.sampled_row_count is None:
                    sampled_value = table.table_statistics.get("sampled_row_count")
                    if sampled_value is not None and table.sampled_row_count != sampled_value:
                        table.sampled_row_count = sampled_value
                        changed = True
                if table.profiled_at is None:
                    profiled_value = table.table_statistics.get("profiled_at")
                    profiled_at = _parse_datetime(profiled_value)
                    if profiled_at and table.profiled_at != profiled_at:
                        table.profiled_at = profiled_at
                        changed = True

            if table.schema_definition is None:
                table.schema_definition = {}

            if is_new:
                created += 1
            elif changed:
                updated += 1

            serialised.append(_serialise_table(table))

        session.flush()

    return jsonify({"created": created, "updated": updated, "sources": serialised})


@bp.post("/profile")
def profile_source():
    """Update profiling statistics for a source."""

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

            preview = summarise_preview(rows)
            profiled_at = _parse_datetime(preview.get("profiled_at")) or datetime.now(
                timezone.utc
            )

            table.sampled_row_count = preview["sampled_row_count"]
            table.profiled_at = profiled_at
            if total_rows is not None:
                table.row_count = total_rows

            stats_update: dict[str, Any] = {
                "profiled_at": preview["profiled_at"],
                "sampled_row_count": preview["sampled_row_count"],
                "columns": preview.get("columns", {}),
                "preview_rows": preview.get("preview_rows"),
            }
            if total_rows is not None:
                stats_update["row_count"] = total_rows
            elif table.row_count is not None:
                stats_update["row_count"] = table.row_count

            table.table_statistics = merge_statistics(table.table_statistics, stats_update)

    with get_db() as session:
        systems = _service.list_systems(session)
    return render_template("sources.html", sources=systems)


__all__ = ["bp"]
