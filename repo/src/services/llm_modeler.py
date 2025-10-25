"""Orchestration layer for generating model drafts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.orm import Session

from src.models.tables import Attribute, DataModel, Entity, Relationship
from src.services.context_builder import DomainContext, build_prompt, load_context
from src.services.impact import ImpactItem, evaluate_model_impact
from src.services.llm_client import LLMClient
from src.services.settings import DEFAULT_USER_ID, get_user_settings
from src.services.validators import DraftRequest


@dataclass(slots=True)
class DraftResult:
    """Result returned by :class:`ModelingService`."""

    model: DataModel
    entities: list[Entity]
    impact: list[ImpactItem]


class ModelingService:
    """Generates model drafts using the language model."""

    def __init__(self, *, user_id: str = DEFAULT_USER_ID) -> None:
        self._user_id = user_id

    def generate_draft(self, session: Session, request: DraftRequest) -> DraftResult:
        context = load_context(session, request.domain_id)
        previous_entities = list(context.entities)
        prompt = build_prompt(context, request.instructions)
        user_settings = get_user_settings(session, self._user_id)
        client = LLMClient(user_settings)
        payload = client.generate_model_payload(prompt)

        model = self._persist_model(session, context, payload, request.instructions)

        change_hints = payload.get("changes")
        if isinstance(change_hints, str):
            hints_iter: list[str] | None = [change_hints]
        elif isinstance(change_hints, list):
            hints_iter = [str(item) for item in change_hints if str(item).strip()]
        else:
            hints_iter = None

        impact = evaluate_model_impact(previous_entities, model.domain.entities, hints_iter)

        return DraftResult(model=model, entities=model.domain.entities, impact=impact)

    def _persist_model(
        self,
        session: Session,
        context: DomainContext,
        payload: Mapping[str, Any],
        instructions: str | None,
    ) -> DataModel:
        domain = context.domain

        name = str(payload.get("name") or f"{domain.name} Model").strip()
        summary = str(payload.get("summary") or "Model summary pending review.").strip()
        definition = str(payload.get("definition") or "").strip()
        if not definition:
            raise ValueError("Model definition missing from LLM response")

        # Replace existing entities and relationships for the domain.
        for relationship in list(domain.relationships):
            session.delete(relationship)
        for entity in list(domain.entities):
            session.delete(entity)
        session.flush()

        entities = self._build_entities(domain, payload)
        for entity in entities:
            session.add(entity)
        session.flush()

        relationships = self._build_relationships(domain, entities, payload)
        for relationship in relationships:
            session.add(relationship)

        model = DataModel(
            domain=domain,
            name=name or f"{domain.name} Model",
            summary=summary or "Model summary pending review.",
            definition=definition,
            instructions=instructions.strip() if instructions else None,
        )
        session.add(model)
        session.flush()

        return model

    def _build_entities(self, domain: Any, payload: Mapping[str, Any]) -> list[Entity]:
        entities: list[Entity] = []
        raw_entities = payload.get("entities")
        if isinstance(raw_entities, list):
            for index, item in enumerate(raw_entities, start=1):
                if not isinstance(item, dict):
                    continue
                entity_name = str(item.get("name") or f"{domain.name} Entity {index}").strip()
                entity = Entity(
                    domain=domain,
                    name=entity_name,
                    description=(str(item.get("description")) or "").strip() or None,
                    documentation=(str(item.get("documentation")) or "").strip() or None,
                )
                attributes_raw = item.get("attributes")
                if isinstance(attributes_raw, list):
                    for attribute_item in attributes_raw:
                        if not isinstance(attribute_item, dict):
                            continue
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
        if not entities:
            # Fall back to a single entity describing the domain using the definition.
            entities.append(
                Entity(
                    domain=domain,
                    name=f"{domain.name} Entity",
                    description=payload.get("summary"),
                    documentation=payload.get("definition"),
                )
            )
        return entities

    def _build_relationships(
        self, domain: Any, entities: list[Entity], payload: Mapping[str, Any]
    ) -> list[Relationship]:
        relationships: list[Relationship] = []
        name_to_entity = {entity.name: entity for entity in entities}
        relationships_raw = payload.get("relationships")
        if isinstance(relationships_raw, list):
            for item in relationships_raw:
                if not isinstance(item, dict):
                    continue
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
                    or "relates to"
                ).strip()
                relationships.append(
                    Relationship(
                        domain=domain,
                        from_entity=name_to_entity[from_name],
                        to_entity=name_to_entity[to_name],
                        relationship_type=relationship_type,
                        description=(str(item.get("description")) or "").strip() or None,
                    )
                )
        return relationships


__all__ = ["DraftResult", "ModelingService"]

