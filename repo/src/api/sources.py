"""REST API for managing imported source metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from flask import Blueprint, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.db import get_db
from src.models.tables import SourceSystem, SourceTable

bp = Blueprint("sources_api", __name__)

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


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _profile_preview(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Return profiling statistics for preview rows."""

    column_names = sorted({key for row in rows for key in row})
    columns: dict[str, Any] = {}
    for name in column_names:
        values = [row.get(name) for row in rows]
        non_null = [value for value in values if value is not None]
        stats = {
            "total": len(values),
            "null_count": len(values) - len(non_null),
            "distinct_count": len({json.dumps(value, sort_keys=True) for value in non_null}),
        }
        if non_null:
            stats["examples"] = non_null[:5]
        columns[name] = {"statistics": stats}
    return {
        "columns": columns,
        "sampled_row_count": len(rows),
    }


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
            if not isinstance(entry, Mapping):
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
            if stats is not None and table.table_statistics != stats:
                table.table_statistics = stats
                changed = True

            if "row_count" in entry:
                row_count = entry.get("row_count")
                if table.row_count != row_count:
                    table.row_count = row_count
                    changed = True

            if "sampled_row_count" in entry:
                sampled = entry.get("sampled_row_count")
                if table.sampled_row_count != sampled:
                    table.sampled_row_count = sampled
                    changed = True

            if "profiled_at" in entry and entry.get("profiled_at"):
                profiled_at = _parse_datetime(entry.get("profiled_at"))
                if profiled_at and table.profiled_at != profiled_at:
                    table.profiled_at = profiled_at
                    changed = True

            if table.schema_definition is None:
                table.schema_definition = {}
            if table.table_statistics is None:
                table.table_statistics = {}

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

    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify({"error": "Profile payload must include a table name."}), 400

    preview_rows = payload.get("preview_rows") or payload.get("rows") or []
    if not isinstance(preview_rows, list):
        return jsonify({"error": "preview_rows must be a list"}), 400

    try:
        with get_db() as session:
            table = _find_table_by_name(session, name)
            if table is None:
                return jsonify({"error": f"Source '{name}' was not found."}), 404

            profiled_at = datetime.now(timezone.utc)
            table.profiled_at = profiled_at
            table.sampled_row_count = len(preview_rows)

            row_count = payload.get("row_count")
            if isinstance(row_count, int) or isinstance(row_count, float):
                table.row_count = int(row_count)

            stats_update = _profile_preview(preview_rows)
            stats_update["profiled_at"] = profiled_at.isoformat()
            if table.row_count is not None:
                stats_update["row_count"] = table.row_count

            table.table_statistics = stats_update

            serialised = _serialise_table(table)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"source": serialised})


__all__ = ["bp"]
