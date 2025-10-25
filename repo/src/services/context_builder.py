"""Build compact JSON context for a domain."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models.tables import (
    Domain,
    DomainEntity,
    EntityAttribute,
    EntityRelationship,
    EntitySourceLink,
)

_TOKEN_CHAR_RATIO = 4
_DOMAIN_RULE_LIMIT = 220
_ENTITY_RULE_LIMIT = 160
_CHILD_RULE_LIMIT = 120


def compact_prior_context(db: Session, domain_name: str, token_budget: int = 10000) -> str:
    """Return a JSON summary of an existing domain trimmed to the token budget."""

    if token_budget <= 0:
        raise ValueError("token_budget must be positive")

    domain = (
        db.execute(
            select(Domain)
            .options(
                selectinload(Domain.entities)
                .selectinload(DomainEntity.attributes),
                selectinload(Domain.entities)
                .selectinload(DomainEntity.outbound_relationships)
                .selectinload(EntityRelationship.child_entity),
                selectinload(Domain.entities)
                .selectinload(DomainEntity.source_links)
                .selectinload(EntitySourceLink.source_table),
            )
            .where(Domain.name == domain_name)
        )
        .scalars()
        .first()
    )
    if domain is None:
        raise ValueError("Domain not found")

    payload: dict[str, Any] = {"domain": {"name": domain.name}}

    domain_rules = _compact_text(domain.description, _DOMAIN_RULE_LIMIT)
    if domain_rules:
        payload["domain"]["rules"] = domain_rules

    entity_lookup = {entity.id: entity.name for entity in domain.entities}
    entities_data = []
    for entity in sorted(domain.entities, key=lambda item: item.name.lower()):
        entity_dict = _serialise_entity(entity, entity_lookup)
        if entity_dict:
            entities_data.append(entity_dict)
    if entities_data:
        payload["entities"] = entities_data

    return _enforce_budget(payload, token_budget)


def _serialise_entity(entity: DomainEntity, entity_lookup: dict[int, str]) -> dict[str, Any]:
    attributes = [_serialise_attribute(attribute) for attribute in sorted(
        entity.attributes,
        key=lambda item: (not item.is_primary_key, item.name.lower()),
    )]
    attributes = [item for item in attributes if item]

    relationships = [_serialise_relationship(relationship, entity_lookup) for relationship in sorted(
        entity.outbound_relationships,
        key=lambda item: item.name.lower(),
    )]
    relationships = [item for item in relationships if item]

    sources = [_serialise_source(link) for link in sorted(
        entity.source_links,
        key=lambda item: (not item.is_primary_source, item.source_table.name if item.source_table else ""),
    )]
    sources = [item for item in sources if item]

    entity_dict: dict[str, Any] = {"name": entity.name}
    if entity.classification:
        entity_dict["type"] = entity.classification
    if entity.is_link:
        entity_dict["link"] = True

    rules = _compact_text(entity.business_rules, _ENTITY_RULE_LIMIT)
    if rules:
        entity_dict["rules"] = rules
    if attributes:
        entity_dict["attributes"] = attributes
    if relationships:
        entity_dict["relationships"] = relationships
    if sources:
        entity_dict["sources"] = sources

    return entity_dict


def _serialise_attribute(attribute: EntityAttribute) -> dict[str, Any] | None:
    attribute_dict: dict[str, Any] = {
        "name": attribute.name,
        "type": attribute.data_type,
        "nullable": bool(attribute.is_nullable),
    }
    if attribute.is_primary_key:
        attribute_dict["key"] = True
    if attribute.is_unique:
        attribute_dict["unique"] = True

    rules = _compact_text(attribute.business_rules, _CHILD_RULE_LIMIT)
    if rules:
        attribute_dict["rules"] = rules

    return attribute_dict


def _serialise_relationship(
    relationship: EntityRelationship, entity_lookup: dict[int, str]
) -> dict[str, Any] | None:
    if relationship.child_entity_id not in entity_lookup:
        return None

    rel_dict: dict[str, Any] = {
        "name": relationship.name,
        "to": entity_lookup[relationship.child_entity_id],
    }
    if relationship.cardinality:
        rel_dict["cardinality"] = relationship.cardinality
    rel_dict["optional"] = bool(relationship.is_optional)
    if relationship.is_identifying:
        rel_dict["identifying"] = True

    rules = _compact_text(relationship.business_rules, _CHILD_RULE_LIMIT)
    if rules:
        rel_dict["rules"] = rules

    return rel_dict


def _serialise_source(link: EntitySourceLink) -> dict[str, Any] | None:
    table = link.source_table
    if table is None:
        return None

    source_dict: dict[str, Any] = {"name": table.name}
    if table.schema_name:
        source_dict["schema"] = table.schema_name
    source_dict["primary"] = bool(link.is_primary_source)
    source_dict["authoritative"] = bool(table.is_authoritative)
    if table.refresh_cadence:
        source_dict["refresh"] = table.refresh_cadence

    rules = _compact_text(link.business_rules or table.business_rules, _CHILD_RULE_LIMIT)
    if rules:
        source_dict["rules"] = rules

    return source_dict


def _compact_text(value: str | None, max_length: int) -> str | None:
    if not value:
        return None
    text = value.strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "\u2026"


def _enforce_budget(payload: dict[str, Any], token_budget: int) -> str:
    max_chars = token_budget * _TOKEN_CHAR_RATIO

    json_payload = _encode_json(payload)
    if len(json_payload) <= max_chars:
        return json_payload

    _trim_rules(payload)
    json_payload = _encode_json(payload)
    if len(json_payload) <= max_chars:
        return json_payload

    while len(json_payload) > max_chars and _remove_last_detail(payload):
        json_payload = _encode_json(payload)
    return json_payload


def _trim_rules(payload: dict[str, Any]) -> None:
    domain = payload.get("domain", {})
    if "rules" in domain:
        domain["rules"] = _compact_text(domain["rules"], _DOMAIN_RULE_LIMIT // 2) or domain["rules"]
    for entity in payload.get("entities", []):
        if "rules" in entity:
            entity["rules"] = _compact_text(entity["rules"], _ENTITY_RULE_LIMIT // 2) or entity["rules"]
        for key in ("attributes", "relationships", "sources"):
            for item in entity.get(key, []) or []:
                if "rules" in item:
                    item["rules"] = _compact_text(item["rules"], _CHILD_RULE_LIMIT // 2) or item["rules"]


def _remove_last_detail(payload: dict[str, Any]) -> bool:
    entities = payload.get("entities") or []
    if not entities:
        domain_rules = payload.get("domain", {}).pop("rules", None)
        return bool(domain_rules)

    entity = entities[-1]
    for key in ("attributes", "relationships", "sources"):
        items = entity.get(key)
        if items:
            items.pop()
            if not items:
                entity.pop(key, None)
            return True

    if entity.pop("rules", None) is not None:
        return True
    if entity.pop("type", None) is not None:
        return True
    if entity.pop("link", None) is not None:
        return True

    entities.pop()
    if not entities:
        payload.pop("entities", None)
    return True


def _encode_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
