"""Prompt builders for the modelling workflows."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.tables import Attribute, Entity, Relationship
from src.services.context_builder import build_prompt, load_context
from src.services.impact import compute_impact
from src.services.llm_client import LLMClient
from src.services.settings import DEFAULT_USER_ID, get_user_settings
from src.services.validators import DraftRequest


@dataclass(slots=True)
class DraftResult:
    """Structured response returned to the API layer."""

    entities: list[Entity]
    impact: list[str]


class ModelingService:
    """Coordinates prompt building, LLM invocation and persistence."""

    def generate_draft(
        self,
        session: Session,
        request: DraftRequest,
        *,
        user_id: str = DEFAULT_USER_ID,
    ) -> DraftResult:
        """Create and persist a model draft for the provided domain."""

        context = load_context(session, request.domain_id)
        prompt = build_prompt(context, request.instructions)
        user_settings = get_user_settings(session, user_id)
        client = LLMClient(user_settings)
        payload = client.generate_model_payload(prompt)

        name = str(payload.get("name") or f"{domain.name} Model")
        summary = str(payload.get("summary") or "Model summary pending review.")
        definition = str(payload.get("definition") or "")
        if not definition:
            raise ValueError("Model definition missing from LLM response")

        previous_entities = [
            SimpleNamespace(
                name=entity.name,
                description=entity.description,
                documentation=entity.documentation,
                attributes=[
                    SimpleNamespace(
                        name=attribute.name,
                        data_type=attribute.data_type,
                        description=attribute.description,
                        is_nullable=attribute.is_nullable,
                    )
                    for attribute in entity.attributes
                ],
            )
            for entity in context.entities
        ]

        # Replace existing entities and relationships for the domain with the new snapshot.
        for relationship in list(context.domain.relationships):
            session.delete(relationship)
        for entity in list(context.domain.entities):
            session.delete(entity)
        session.flush()

        entities: list[Entity] = []
        relationships: list[Relationship] = []

        raw_entities = payload.get("entities")
        if isinstance(raw_entities, list) and raw_entities:
            for index, item in enumerate(raw_entities, start=1):
                entity_name = str(item.get("name") or f"{context.domain.name} Entity {index}")
                entity = Entity(
                    domain=context.domain,
                    name=entity_name.strip(),
                    description=(str(item.get("description")) or "").strip() or None,
                    documentation=(str(item.get("documentation")) or "").strip() or None,
                )
                attributes_raw = item.get("attributes")
                if isinstance(attributes_raw, list):
                    for attribute_item in attributes_raw:
                        attr_name = str(attribute_item.get("name") or "").strip()
                        if not attr_name:
                            continue
                        attribute = Attribute(
                            name=attr_name,
                            data_type=(
                                str(attribute_item.get("data_type"))
                                if attribute_item.get("data_type")
                                else None
                            ),
                            description=(
                                str(attribute_item.get("description"))
                                if attribute_item.get("description")
                                else None
                            ),
                            is_nullable=bool(attribute_item.get("is_nullable", True)),
                            default_value=(
                                str(attribute_item.get("default"))
                                if attribute_item.get("default")
                                else None
                            ),
                        )
                        entity.attributes.append(attribute)
                entities.append(entity)
        else:
            if not definition:
                raise ValueError("Model definition missing from LLM response")
            entity = Entity(
                domain=context.domain,
                name=name.strip(),
                description=summary.strip() or None,
                documentation=definition.strip(),
            )
            entities.append(entity)

        name_to_entity = {entity.name: entity for entity in entities}
        relationships_raw = payload.get("relationships")
        if isinstance(relationships_raw, list):
            for item in relationships_raw:
                from_name = str(
                    item.get("from")
                    or item.get("source")
                    or item.get("from_entity")
                    or ""
                ).strip()
                to_name = str(
                    item.get("to")
                    or item.get("target")
                    or item.get("to_entity")
                    or ""
                ).strip()
                if not from_name or not to_name:
                    continue
                if from_name not in name_to_entity or to_name not in name_to_entity:
                    continue
                relationship_type = str(
                    item.get("type")
                    or item.get("relationship_type")
                    or "relates_to"
                ).strip()
                relationship = Relationship(
                    domain=context.domain,
                    from_entity=name_to_entity[from_name],
                    to_entity=name_to_entity[to_name],
                    relationship_type=relationship_type,
                    description=(str(item.get("description")) or "").strip() or None,
                )
                relationships.append(relationship)

        for entity in entities:
            session.add(entity)
        session.flush()
        for relationship in relationships:
            session.add(relationship)
        session.flush()

        change_hints_raw = payload.get("changes")
        if isinstance(change_hints_raw, str):
            change_hints = [change_hints_raw]
        elif isinstance(change_hints_raw, list):
            change_hints = [str(item) for item in change_hints_raw]
        else:
            change_hints = None

        impact = evaluate_model_impact(previous_entities, entities, change_hints)

        return DraftResult(entities=entities, impact=impact)
