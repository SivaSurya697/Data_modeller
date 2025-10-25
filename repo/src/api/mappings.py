"""Endpoints for attribute to source column mappings."""

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import (
    Attribute,
    Entity,
    Mapping,
    MappingStatus,
    SourceTable,
)
from src.services import mapping_planner


bp = Blueprint("mappings_api", __name__)


def _error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _parse_request_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if payload is not None:
        return payload

    if request.form:
        return request.form.to_dict()

    raw = request.data.decode().strip() if request.data else ""
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _serialize_mapping(mapping: Mapping) -> dict[str, Any]:
    return {
        "id": mapping.id,
        "entity_id": mapping.entity_id,
        "attribute_id": mapping.attribute_id,
        "attribute": mapping.attribute.name if mapping.attribute else None,
        "source_table_id": mapping.source_table_id,
        "source_table": (
            f"{mapping.source_table.schema_name}.{mapping.source_table.table_name}"
            if mapping.source_table
            else None
        ),
        "column_path": mapping.column_path,
        "confidence": mapping.confidence,
        "status": mapping.status.value if isinstance(mapping.status, MappingStatus) else mapping.status,
        "rationale": mapping.rationale,
        "transforms_json": mapping.transforms_json,
        "join_recipe": mapping.join_recipe,
    }


@bp.route("/autoplan", methods=["POST"])
def autoplan_mappings():
    payload = _parse_request_payload()
    entity_id_raw = payload.get("entity_id")
    if entity_id_raw is None:
        return _error("entity_id is required")

    try:
        entity_id = int(entity_id_raw)
    except (TypeError, ValueError):
        return _error("entity_id must be an integer")

    with get_db() as session:
        entity = session.get(Entity, entity_id)
        if entity is None:
            return _error(f"Entity {entity_id} was not found", status=404)

        attributes = (
            session.execute(
                select(Attribute).where(Attribute.entity_id == entity_id).order_by(Attribute.name)
            )
            .scalars()
            .all()
        )

        sources = (
            session.execute(
                select(SourceTable)
                .options(joinedload(SourceTable.columns))
                .order_by(SourceTable.schema_name, SourceTable.table_name)
            )
            .unique()
            .scalars()
            .all()
        )

        attribute_index = {attribute.id: attribute for attribute in attributes}

        attr_payload = [
            {
                "id": attribute.id,
                "name": attribute.name,
                "datatype": attribute.data_type,
                "data_type": attribute.data_type,
                "semantic_type": getattr(attribute, "semantic_type", None),
                "required": not attribute.is_nullable,
            }
            for attribute in attributes
        ]

        source_payload = []
        for table in sources:
            table_name = f"{table.schema_name}.{table.table_name}" if table.schema_name else table.table_name
            schema_json = {column.name: column.data_type or "" for column in table.columns}
            stats_json = {column.name: column.statistics or {} for column in table.columns}
            source_payload.append(
                {
                    "id": table.id,
                    "name": table_name,
                    "schema_json": schema_json,
                    "stats_json": stats_json,
                }
            )

        autoplan_result = mapping_planner.autoplan(
            {"id": entity.id, "name": entity.name}, attr_payload, source_payload
        )

        created_count = 0
        persisted: dict[int, Mapping] = {}

        for item in autoplan_result:
            attr_id = item.get("attribute_id")
            candidates = item.get("candidates") or []
            if not attr_id or not candidates:
                continue

            top_candidate = candidates[0]
            source_table_id = top_candidate.get("source_table_id")
            column_path = top_candidate.get("column_path")
            confidence = top_candidate.get("confidence")
            rationale = top_candidate.get("rationale")

            if source_table_id is None:
                continue

            existing = (
                session.execute(
                    select(Mapping)
                    .where(
                        Mapping.attribute_id == attr_id,
                        Mapping.status == MappingStatus.DRAFT,
                    )
                    .limit(1)
                )
                .scalars()
                .first()
            )

            if existing:
                existing.entity_id = entity_id
                existing.source_table_id = source_table_id
                existing.column_path = column_path
                existing.confidence = confidence
                existing.rationale = rationale
                existing.transforms_json = top_candidate.get("transforms")
                existing.join_recipe = top_candidate.get("join_recipe")
                mapping = existing
            else:
                mapping = Mapping(
                    entity_id=entity_id,
                    attribute_id=attr_id,
                    source_table_id=source_table_id,
                    column_path=column_path,
                    confidence=confidence,
                    rationale=rationale,
                    status=MappingStatus.DRAFT,
                    transforms_json=top_candidate.get("transforms"),
                    join_recipe=top_candidate.get("join_recipe"),
                )
                session.add(mapping)
                created_count += 1

            persisted[attr_id] = mapping

        session.flush()

        view_rows: list[dict[str, Any]] = []
        for item in autoplan_result:
            attr_id = item.get("attribute_id")
            attribute = attribute_index.get(attr_id) if attr_id is not None else None
            mapping = persisted.get(attr_id)
            top_candidate = (item.get("candidates") or [None])[0]
            view_rows.append(
                {
                    "attribute_id": attr_id,
                    "attribute_name": attribute.name if attribute else item.get("attribute"),
                    "mapping_id": mapping.id if mapping else None,
                    "status": (
                        mapping.status.value
                        if mapping and isinstance(mapping.status, MappingStatus)
                        else (mapping.status if mapping else "unmapped")
                    ),
                    "column_path": mapping.column_path if mapping else None,
                    "confidence": mapping.confidence if mapping else None,
                    "rationale": mapping.rationale if mapping else None,
                    "top_candidate": top_candidate,
                    "candidates": item.get("candidates") or [],
                }
            )

    response_payload = {"ok": True, "candidates": autoplan_result, "created": created_count}

    if request.headers.get("HX-Request") == "true":
        return render_template(
            "partials/mapping_results.html",
            rows=view_rows,
            created_count=created_count,
        )

    response_payload["persisted"] = [row for row in view_rows if row["mapping_id"]]
    return jsonify(response_payload)


@bp.route("/<int:mapping_id>", methods=["PATCH"])
def update_mapping(mapping_id: int):
    payload = _parse_request_payload()
    status_raw = payload.get("status")
    if status_raw is None:
        return _error("status is required")

    try:
        status = MappingStatus(status_raw)
    except ValueError:
        valid = ", ".join(status.value for status in MappingStatus)
        return _error(f"status must be one of: {valid}")

    transforms = payload.get("transforms_json")
    if transforms is not None and not isinstance(transforms, (dict, list)):
        return _error("transforms_json must be an object if provided")

    join_recipe = payload.get("join_recipe")
    if join_recipe is not None and not isinstance(join_recipe, str):
        return _error("join_recipe must be a string if provided")

    with get_db() as session:
        mapping = session.get(Mapping, mapping_id)
        if mapping is None:
            return _error(f"Mapping {mapping_id} was not found", status=404)

        mapping.status = status
        if transforms is not None:
            mapping.transforms_json = transforms  # type: ignore[assignment]
        if join_recipe is not None:
            mapping.join_recipe = join_recipe

        session.flush()
        serialized = _serialize_mapping(mapping)

    if request.headers.get("HX-Request") == "true":
        return render_template("partials/mapping_status_badge.html", mapping=serialized)

    return jsonify({"ok": True, "mapping": serialized})


@bp.route("/", methods=["GET"])
def list_mappings():
    entity_id_raw = request.args.get("entity_id")
    if entity_id_raw is None:
        return _error("entity_id query parameter is required")

    try:
        entity_id = int(entity_id_raw)
    except (TypeError, ValueError):
        return _error("entity_id must be an integer")

    with get_db() as session:
        mappings = (
            session.execute(
                select(Mapping)
                .options(
                    joinedload(Mapping.attribute),
                    joinedload(Mapping.source_table),
                )
                .where(Mapping.entity_id == entity_id)
                .order_by(Mapping.id)
            )
            .unique()
            .scalars()
            .all()
        )

    serialized = [_serialize_mapping(mapping) for mapping in mappings]
    return jsonify({"ok": True, "mappings": serialized})


__all__ = ["bp"]

