"""Utilities for proposing and evidencing entity relationships."""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from src.models.tables import Domain, Entity, SourceTable
from src.services.llm_client import LLMClient
from src.services.settings import get_user_settings


def build_model_excerpt(db: Session, domain_name: str) -> dict[str, Any]:
    """Return a lightweight description of the entities for ``domain_name``."""

    domain_stmt = (
        select(Domain)
        .where(Domain.name == domain_name)
        .options(joinedload(Domain.entities).joinedload(Entity.attributes))
    )
    domain = db.execute(domain_stmt).unique().scalar_one_or_none()
    if domain is None:
        raise ValueError(f"Domain '{domain_name}' was not found")

    entities: list[dict[str, Any]] = []
    for entity in sorted(domain.entities, key=lambda ent: ent.name.lower()):
        attributes = [
            {
                "name": attribute.name,
                "datatype": attribute.data_type or "unknown",
            }
            for attribute in sorted(entity.attributes, key=lambda attr: attr.name.lower())
        ]
        entities.append(
            {
                "id": entity.id,
                "name": entity.name,
                "role": getattr(entity.role, "value", str(entity.role)),
                "attributes": attributes,
            }
        )

    return {"entities": entities}


def llm_propose_relationships(
    db: Session, user_id: int | str, model_excerpt_json: str
) -> dict[str, Any]:
    """Return relationship proposals produced by the language model."""

    settings = get_user_settings(db, str(user_id))
    client = LLMClient(settings)
    messages = [
        {
            "role": "system",
            "content": (
                "You propose FACT→DIM relationships and cardinalities for a "
                "healthcare payor logical model. Output STRICT JSON: { "
                "'proposed_relationships':[{'from','to','type','rule'}], "
                "'rationales':[...]}."
            ),
        },
        {"role": "user", "content": f"Model excerpt: {model_excerpt_json}"},
    ]

    payload = client.json_chat_complete(messages)
    if not isinstance(payload, Mapping):
        raise RuntimeError("LLM response did not return a JSON object")

    # Ensure the expected keys exist even when the model omits them.
    if "proposed_relationships" not in payload:
        payload = dict(payload)
        payload["proposed_relationships"] = []

    return dict(payload)


def evidence_for_fk(
    stats_child: Mapping[str, Any] | None,
    stats_parent: Mapping[str, Any] | None,
    child_key: str,
    parent_key: str,
) -> dict[str, float | None]:
    """Compute simple coverage evidence for a proposed foreign key."""

    coverage: float | None = None
    child_per_parent: float | None = None

    if stats_child:
        null_pct = _coerce_float(
            stats_child.get("null_pct")
            or stats_child.get("null_percent")
            or stats_child.get("null_ratio")
        )
        if null_pct is not None:
            # Normalise percentages that might be expressed as 0-100.
            if null_pct > 1:
                null_pct = null_pct / 100 if null_pct <= 100 else 1.0
            null_pct = max(0.0, min(null_pct, 1.0))
            coverage = 1.0 - null_pct

    child_row_count = _coerce_float(
        (stats_child or {}).get("row_count")
        or (stats_child or {}).get("count")
        or (stats_child or {}).get("non_null_count")
    )
    parent_distinct = _coerce_float(
        (stats_parent or {}).get("distinct_count")
        or (stats_parent or {}).get("distinct")
        or (stats_parent or {}).get("unique_count")
    )

    if child_row_count is not None and parent_distinct and parent_distinct > 0:
        child_per_parent = child_row_count / parent_distinct
        if math.isfinite(child_per_parent):
            child_per_parent = float(child_per_parent)
        else:
            child_per_parent = None

    return {
        "coverage": coverage,
        "child_per_parent_mean": child_per_parent,
    }


def enrich_with_evidence(
    db: Session, proposals: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Attach deterministic evidence to relationship proposals."""

    proposals_list = [dict(proposal) for proposal in proposals]
    if not proposals_list:
        return []

    raw_entity_names = {
        str(proposal.get("from") or "").strip()
        for proposal in proposals_list
    } | {
        str(proposal.get("to") or "").strip()
        for proposal in proposals_list
    }
    raw_entity_names.discard("")

    entities: list[Entity] = []
    if raw_entity_names:
        entity_stmt = (
            select(Entity)
            .where(func.lower(Entity.name).in_({name.lower() for name in raw_entity_names}))
            .options(joinedload(Entity.attributes))
        )
        entities = db.execute(entity_stmt).unique().scalars().all()
    entity_lookup = {entity.name.lower(): entity for entity in entities}

    tables = db.execute(
        select(SourceTable).options(joinedload(SourceTable.columns))
    ).unique().scalars().all()
    table_lookup = _build_table_lookup(tables)
    stats_lookup = _build_stats_lookup(tables)

    results: list[dict[str, Any]] = []
    for proposal in proposals_list:
        from_name = str(proposal.get("from") or "").strip()
        to_name = str(proposal.get("to") or "").strip()
        proposed_type = str(proposal.get("type") or "one_to_many").strip()

        from_entity = entity_lookup.get(from_name.lower())
        to_entity = entity_lookup.get(to_name.lower())
        child_key = _guess_key_name(from_entity.attributes if from_entity else [])
        parent_key = _guess_key_name(to_entity.attributes if to_entity else [])

        evidence = {"coverage": None, "child_per_parent_mean": None}

        if from_entity and to_entity and child_key and parent_key:
            from_table = table_lookup.get(_normalise_identifier(from_entity.name))
            to_table = table_lookup.get(_normalise_identifier(to_entity.name))
            child_stats = None
            parent_stats = None
            if from_table:
                child_stats = dict(stats_lookup.get(from_table.id, {}).get(child_key.lower(), {}))
                if from_table.row_count is not None and "row_count" not in child_stats:
                    child_stats["row_count"] = from_table.row_count
            if to_table:
                parent_stats = dict(stats_lookup.get(to_table.id, {}).get(parent_key.lower(), {}))
            evidence = evidence_for_fk(child_stats, parent_stats, child_key, parent_key)

        child_mean = evidence.get("child_per_parent_mean")
        classification = classify_cardinality(child_mean)
        if classification:
            adjusted_type = classification
        else:
            adjusted_type = proposed_type

        results.append(
            {
                "from": from_name,
                "to": to_name,
                "type": adjusted_type,
                "rule": proposal.get("rule"),
                "evidence": evidence,
            }
        )

    return results


def classify_cardinality(child_mean: float | None) -> str:
    """Classify the relationship cardinality from the observed mean."""

    if child_mean is None:
        return "one_to_many"
    if child_mean > 1.2:
        return "one_to_many"
    if 0.8 <= child_mean <= 1.2:
        return "one_to_one"
    return ""


def _guess_key_name(attributes: Iterable[Any]) -> str | None:
    def _score(name: str) -> tuple[int, int]:
        lower = name.lower()
        if lower.endswith("_id"):
            return (0, len(lower))
        if lower == "id":
            return (1, len(lower))
        if lower.endswith("id"):
            return (2, len(lower))
        return (3, len(lower))

    names = [getattr(attribute, "name", "") for attribute in attributes]
    names = [name for name in names if name]
    if not names:
        return None
    names.sort(key=_score)
    return names[0]


def _build_table_lookup(tables: Iterable[SourceTable]) -> dict[str, SourceTable]:
    lookup: dict[str, SourceTable] = {}
    for table in tables:
        candidates = {
            _normalise_identifier(table.table_name),
            _normalise_identifier(table.display_name or ""),
            _normalise_identifier(f"{table.schema_name}_{table.table_name}"),
        }
        for candidate in candidates:
            if candidate and candidate not in lookup:
                lookup[candidate] = table
    return lookup


def _build_stats_lookup(
    tables: Iterable[SourceTable],
) -> dict[int, dict[str, Mapping[str, Any]]]:
    stats: dict[int, dict[str, Mapping[str, Any]]] = {}
    for table in tables:
        column_stats: dict[str, Mapping[str, Any]] = {}
        table_payload = table.table_statistics or {}
        if isinstance(table_payload, Mapping):
            columns = table_payload.get("columns")
            if isinstance(columns, Mapping):
                for column_name, payload in columns.items():
                    if isinstance(payload, Mapping):
                        column_stats[column_name.lower()] = payload
        for column in table.columns:
            if isinstance(column.statistics, Mapping):
                column_stats[column.name.lower()] = column.statistics
        if column_stats:
            stats[table.id] = column_stats
    return stats


def _normalise_identifier(value: str) -> str:
    if not value:
        return ""
    camel_snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", value)
    canonical = re.sub(r"[^a-z0-9]+", "_", camel_snake, flags=re.IGNORECASE)
    canonical = canonical.strip("_").lower()
    return canonical


def _coerce_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


__all__ = [
    "build_model_excerpt",
    "classify_cardinality",
    "enrich_with_evidence",
    "evidence_for_fk",
    "llm_propose_relationships",
]
