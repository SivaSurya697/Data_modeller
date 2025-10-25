"""Orchestration layer for generating model drafts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.tables import (
    Attribute,
    DataModel,
    Entity,
    EntityRole,
    SCDType,
    Relationship,
    RelationshipCardinality,
)
from src.services.context_builder import (
    DomainContext,
    build_critique_messages,
    build_draft_messages,
    load_context,
)
from src.services.impact import ImpactItem, evaluate_model_impact
from src.services.llm_client import LLMClient
from src.services.settings import DEFAULT_USER_ID, get_user_settings
from src.services.validators import (
    DraftRequest,
    EntitySpec,
    ModelDraftPayload,
)
from src.services.model_analysis import infer_model_version
from pydantic import ValidationError


@dataclass(slots=True)
class DraftResult:
    """Result returned by :class:`ModelingService`."""

    model: DataModel
    version: int
    entities: list[Entity]
    relationships: list[Relationship]
    impact: list[ImpactItem]


EnumT = TypeVar("EnumT", bound=Enum)


class ModelingService:
    """Generates model drafts using the language model."""

    def __init__(self, *, user_id: str = DEFAULT_USER_ID) -> None:
        self._user_id = user_id

    def generate_draft(self, session: Session, request: DraftRequest) -> DraftResult:
        context = load_context(session, request.domain_id)
        previous_entities = list(context.entities)
        draft_messages = build_draft_messages(context, request.instructions)
        user_settings = get_user_settings(session, self._user_id)
        client = LLMClient(user_settings)
        payload = client.generate_model_payload(prompt)
        try:
            payload_spec = ModelDraftPayload.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                "Generated draft is missing required metadata; "
                "ensure grain, SCD type, and measure flags are provided"
            ) from exc

        model = self._persist_model(
            session, context, payload, payload_spec, request.instructions
        )

        amendments = critique_payload.get("amendments")
        if isinstance(amendments, Mapping):
            final_payload = self._merge_payloads(final_payload, amendments)

        model = self._persist_model(session, context, final_payload, request.instructions)

        change_hints = final_payload.get("changes")
        if isinstance(change_hints, str):
            hints_iter: list[str] | None = [change_hints]
        elif isinstance(change_hints, list):
            hints_iter = [str(item) for item in change_hints if str(item).strip()]
        else:
            hints_iter = None

        impact = evaluate_model_impact(previous_entities, model.domain.entities, hints_iter)
        version = infer_model_version(model.domain)
        relationships = sorted(
            model.domain.relationships,
            key=lambda rel: (
                rel.from_entity.name.lower(),
                rel.to_entity.name.lower(),
                (rel.relationship_type or ""),
            ),
        )

        return DraftResult(
            model=model,
            version=model.version,
            entities=model.domain.entities,
            relationships=relationships,
            impact=impact,
        )

    def _merge_payloads(
        self,
        base_payload: Mapping[str, Any],
        overlay_payload: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(base_payload)
        if not overlay_payload:
            return merged

        for key, value in overlay_payload.items():
            existing = merged.get(key)
            if isinstance(existing, Mapping) and isinstance(value, Mapping):
                merged[key] = self._merge_payloads(existing, value)
            else:
                merged[key] = value
        return merged

    def _persist_model(
        self,
        session: Session,
        context: DomainContext,
        payload: Mapping[str, Any],
        payload_spec: ModelDraftPayload,
        instructions: str | None,
    ) -> DataModel:
        domain = context.domain

        name = str(
            payload_spec.name or payload.get("name") or f"{domain.name} Model"
        ).strip()
        summary = str(
            payload_spec.summary
            or payload.get("summary")
            or "Model summary pending review."
        ).strip()

        definition_source = payload_spec.definition or payload.get("definition")
        if definition_source is None or not str(definition_source).strip():
            definition_source = (
                payload.get("summary")
                or getattr(context.domain, "description", None)
                or "Model definition pending review."
            )

        definition = str(definition_source or "").strip() or "Model definition pending review."

        # Replace existing entities and relationships for the domain.
        for relationship in list(domain.relationships):
            session.delete(relationship)
        for entity in list(domain.entities):
            session.delete(entity)
        session.flush()

        entities = self._build_entities(
            domain,
            payload_spec.entities,
            summary=summary,
            definition=definition,
        )
        for entity in entities:
            session.add(entity)
        session.flush()

        relationships = self._build_relationships(domain, entities, payload)
        for relationship in relationships:
            session.add(relationship)

        max_version = session.execute(
            select(func.max(DataModel.version)).where(DataModel.domain_id == domain.id)
        ).scalar()
        next_version = int(max_version or 0) + 1

        model = DataModel(
            domain=domain,
            version=next_version,
            name=name or f"{domain.name} Model",
            summary=summary or "Model summary pending review.",
            definition=definition,
            instructions=instructions.strip() if instructions else None,
        )
        session.add(model)
        session.flush()

        return model

    def _build_entities(
        self,
        domain: Any,
        entities_spec: Sequence[EntitySpec],
        *,
        summary: str | None,
        definition: str | None,
    ) -> list[Entity]:
        entities: list[Entity] = []
        for index, item in enumerate(entities_spec, start=1):
            entity_name = item.name or f"{domain.name} Entity {index}"
            entity = Entity(
                domain=domain,
                name=entity_name,
                description=(item.description or "").strip() or None,
                documentation=(item.documentation or "").strip() or None,
                role=item.role,
                grain_json=item.grain,
                scd_type=item.scd_type,
            )
            attribute_lookup: dict[str, Attribute] = {}
            for attribute_item in item.attributes:
                attr_name = attribute_item.name.strip()
                attribute = Attribute(
                    name=attr_name,
                    data_type=(attribute_item.data_type or "").strip() or None,
                    description=(attribute_item.description or "").strip() or None,
                    is_nullable=bool(attribute_item.is_nullable),
                    default_value=(
                        str(attribute_item.default).strip()
                        if attribute_item.default is not None
                        else None
                    ),
                    is_measure=bool(attribute_item.is_measure),
                    is_surrogate_key=bool(attribute_item.is_surrogate_key),
                )
                entity.attributes.append(attribute)
                attribute_lookup[attr_name.lower()] = attribute

            missing_grain = [
                grain_name
                for grain_name in item.grain
                if grain_name.lower().strip() not in attribute_lookup
            ]
            if missing_grain:
                missing = ", ".join(sorted(set(missing_grain)))
                raise ValueError(
                    f"Entity '{entity_name}' references unknown grain attributes: {missing}"
                )
            entities.append(entity)
        if not entities:
            # Fall back to a single entity describing the domain using the definition.
            entities.append(
                Entity(
                    domain=domain,
                    name=f"{domain.name} Entity",
                    description=summary,
                    documentation=definition,
                    role=EntityRole.UNKNOWN,
                    grain_json=[],
                    scd_type=SCDType.NONE,
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
                cardinality_from = self._coerce_enum(
                    item.get("cardinality_from")
                    or item.get("from_cardinality")
                    or item.get("source_cardinality"),
                    enum_cls=RelationshipCardinality,
                    field_name="cardinality_from",
                    context=f"Relationship {from_name} -> {to_name}",
                )
                cardinality_to = self._coerce_enum(
                    item.get("cardinality_to")
                    or item.get("to_cardinality")
                    or item.get("target_cardinality"),
                    enum_cls=RelationshipCardinality,
                    field_name="cardinality_to",
                    context=f"Relationship {from_name} -> {to_name}",
                )
                relationships.append(
                    Relationship(
                        domain=domain,
                        from_entity=name_to_entity[from_name],
                        to_entity=name_to_entity[to_name],
                        relationship_type=relationship_type,
                        description=(str(item.get("description")) or "").strip() or None,
                        cardinality_from=cardinality_from,
                        cardinality_to=cardinality_to,
                    )
                )
        return relationships

    @staticmethod
    def _coerce_enum(
        value: Any,
        *,
        enum_cls: type[EnumT],
        field_name: str,
        context: str,
    ) -> EnumT:
        if isinstance(value, enum_cls):
            return value
        if value is None:
            raise ValueError(f"{context} must include '{field_name}'")
        text = str(value).strip().lower()
        for member in enum_cls:  # type: ignore[call-arg]
            if getattr(member, "value", None) == text:
                return member
        valid_values = ", ".join(member.value for member in enum_cls)  # type: ignore[attr-defined]
        raise ValueError(
            f"{context} has invalid {field_name} '{value}'. Expected one of: {valid_values}"
        )


__all__ = ["DraftResult", "ModelingService"]

