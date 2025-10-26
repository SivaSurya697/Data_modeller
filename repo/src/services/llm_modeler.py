"""Orchestration layer for generating model drafts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.tables import (
    Attribute,
    DataModel,
    Domain,
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
from src.services import validators
from src.services.validators import DraftRequest, EntitySpec, ModelDraftPayload
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

_LOGGER = logging.getLogger(__name__)

SYSTEM_FRESH = """
You are a senior healthcare payor data modeller.
Produce a LOGICAL model with STAR/SNOWFLAKE discipline:
- Classify each entity as "role": "fact" or "dimension" (use "other" only if unavoidable).
- FACTS: must include "grain_json" (list of key columns) AND at least one attribute with "is_measure": true.
- DIMENSIONS: must include "scd_type" in {"none","scd1","scd2"} AND at least one primary/natural key.
- For every entity: include keys[], attributes[] with {name, datatype, semantic_type, required, [is_measure? bool], [is_surrogate_key? bool]}.
- Define relationships with explicit cardinalities (one_to_many, many_to_one, one_to_one, many_to_many) and a short rule.
- Use snake_case for all names. Do not mirror raw sources. Prefer canonical payor constructs.
Output STRICT JSON with keys: entities, relationships, dictionary, shared_dim_refs. No prose.
"""

SYSTEM_REFINE = """
You are a modelling reviewer. Fix ONLY metadata gaps without renaming existing fields unless required:
- Add "grain_json" to every FACT if missing; pick keys consistent with attributes and relationships.
- Ensure every FACT has at least one attribute with "is_measure": true (choose appropriate numeric measures).
- Add "scd_type" to every DIMENSION if missing; prefer "scd1" unless historical tracking is evident, then "scd2".
Return STRICT JSON: {"amended_model": <full corrected model>}. No commentary.
"""

_METADATA_ISSUE_PATTERNS: tuple[str, ...] = (
    "must define a non-empty grain",
    "must include at least one measure",
    "must declare an scd type",
)


def _issues_are_metadata_only(issues: Sequence[str]) -> bool:
    """Return ``True`` when all issues relate to grain, measures, or SCD metadata."""

    filtered = [issue.strip() for issue in issues if isinstance(issue, str) and issue.strip()]
    if not filtered:
        return False
    for issue in filtered:
        lower_issue = issue.lower()
        if not any(pattern in lower_issue for pattern in _METADATA_ISSUE_PATTERNS):
            return False
    return True


def _build_fresh_user_prompt(context: DomainContext, instructions: str | None) -> str:
    """Assemble the user prompt for the fresh draft pass."""

    sections = context.to_prompt_sections()
    if instructions:
        instructions_clean = instructions.strip()
        if instructions_clean:
            sections.append(f"Additional instructions:\n{instructions_clean}")
    sections.append(
        "Task: Draft a fresh logical data model in JSON following the system instructions. "
        "Emphasise canonical payor facts and dimensions with complete metadata."
    )
    return "\n\n".join(sections)


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
        payload = client.generate_draft_payload(draft_messages)
        critique_messages = build_critique_messages(
            context, request.instructions, payload
        )
        critique_payload, amended_payload = client.generate_critique_payload(
            critique_messages
        )

        final_payload = self._merge_payloads(payload, amended_payload)

        critique_amendments = critique_payload.get("amendments")
        if isinstance(critique_amendments, Mapping):
            final_payload = self._merge_payloads(final_payload, critique_amendments)

        try:
            payload_spec = ModelDraftPayload.model_validate(final_payload)
        except ValidationError as exc:
            raise ValueError(
                "Generated draft is missing required metadata; "
                "ensure grain, SCD type, and measure flags are provided"
            ) from exc

        model = self._persist_model(
            session, context, final_payload, payload_spec, request.instructions
        )

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


def refine_model_for_metadata(db, user_id: int, model_json_str: str) -> str:
    """Request a metadata-only refinement pass from the language model."""

    settings = get_user_settings(db, str(user_id))
    client = LLMClient(settings)
    messages = [
        {"role": "system", "content": SYSTEM_REFINE.strip()},
        {
            "role": "user",
            "content": f"Original model JSON:\n{model_json_str}",
        },
    ]
    payload = client.json_chat_complete(messages, temperature=0.1, max_tokens=3500)
    amended_raw = payload.get("amended_model") if isinstance(payload, Mapping) else None
    if isinstance(amended_raw, Mapping):
        amended_model = dict(amended_raw)
    elif isinstance(amended_raw, str):
        sanitized = LLMClient._sanitize_response(amended_raw)
        try:
            parsed = json.loads(sanitized)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
            raise RuntimeError("Refine response did not contain valid JSON") from exc
        if not isinstance(parsed, Mapping):
            raise RuntimeError("Refine response did not include a JSON object")
        amended_model = dict(parsed)
    else:
        raise RuntimeError("Refine response missing 'amended_model'")

    amended_model.setdefault("dictionary", [])
    amended_model.setdefault("shared_dim_refs", [])
    if "relationships" not in amended_model:
        amended_model["relationships"] = []

    amended_json = json.dumps(amended_model, ensure_ascii=False)
    _LOGGER.info("Refine metadata payload generated length=%s", len(amended_json))
    return amended_json


def draft_fresh(
    db: Session,
    *,
    domain_name: str,
    user_id: int | str = DEFAULT_USER_ID,
    instructions: str | None = None,
) -> tuple[str, bool, dict[str, Any]]:
    """Generate a fresh model draft and optionally trigger metadata refinement."""

    if not domain_name:
        raise ValueError("Domain name must be provided")

    domain_stmt = select(Domain).where(func.lower(Domain.name) == domain_name.lower())
    domain = db.execute(domain_stmt).scalar_one_or_none()
    if domain is None:
        raise ValueError(f"Domain '{domain_name}' was not found")

    context = load_context(db, domain.id)
    instructions_text = instructions if instructions is None else str(instructions)
    user_prompt = _build_fresh_user_prompt(context, instructions_text)

    user_identifier = str(user_id)
    settings = get_user_settings(db, user_identifier)
    client = LLMClient(settings)
    messages = [
        {"role": "system", "content": SYSTEM_FRESH.strip()},
        {"role": "user", "content": user_prompt},
    ]
    payload_raw = client.json_chat_complete(messages, temperature=0.1, max_tokens=3500)
    if not isinstance(payload_raw, Mapping):
        raise RuntimeError("LLM response did not return a JSON object")

    payload = dict(payload_raw)
    payload.setdefault("entities", [])
    payload.setdefault("relationships", [])
    payload.setdefault("dictionary", [])
    payload.setdefault("shared_dim_refs", [])

    model_json_str = json.dumps(payload, ensure_ascii=False)
    entity_count = len(payload.get("entities", [])) if isinstance(payload.get("entities"), list) else 0
    _LOGGER.info(
        "Draft fresh model generated length=%s entities=%s",
        len(model_json_str),
        entity_count,
    )

    context_used = {
        "domain_id": context.domain.id,
        "domain_name": context.domain.name,
        "domain_description": context.domain.description,
        "existing_entity_count": len(context.entities),
        "existing_relationship_count": len(context.relationships),
        "change_set_count": len(context.change_sets),
        "instructions_supplied": bool(instructions_text and instructions_text.strip()),
    }

    validation = validators.validate_model_json(model_json_str)
    issues = validation.get("issues", []) if isinstance(validation, Mapping) else []
    if validation.get("ok", False):
        return model_json_str, False, context_used

    if _issues_are_metadata_only(issues):
        try:
            refined_json_str = refine_model_for_metadata(db, user_identifier, model_json_str)
        except RuntimeError as exc:
            error = RuntimeError("Draft failed after refine")
            error.issues = list(issues)
            error.model_json = model_json_str
            error.autorefined = True
            error.context_used = context_used
            raise error from exc

        refined_validation = validators.validate_model_json(refined_json_str)
        if refined_validation.get("ok", False):
            return refined_json_str, True, context_used

        error = RuntimeError("Draft failed after refine")
        error.issues = refined_validation.get("issues", [])
        error.model_json = refined_json_str
        error.autorefined = True
        error.context_used = context_used
        raise error

    return model_json_str, False, context_used


def draft_extend(
    session: Session,
    *,
    domain: str,
    prior_excerpt_json: str,
    user_id: int | str = DEFAULT_USER_ID,
) -> str:
    """Request a model extension diff from the language model."""

    user_identifier = str(user_id)
    settings = get_user_settings(session, user_identifier)
    client = LLMClient(settings)
    system_message = (
        "You are a senior dimensional modeller extending an existing model. "
        "Return JSON with 'proposed_changes' and 'dictionary_updates'."
    )
    user_message = (
        f"Generate an extension diff for the domain '{domain}'.\n"
        "Baseline model JSON:\n"
        f"{prior_excerpt_json}\n"
        "Respond strictly with JSON."
    )
    payload = client.json_chat_complete(
        [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
    )
    return json.dumps(payload)


__all__ = [
    "DraftResult",
    "ModelingService",
    "draft_extend",
    "draft_fresh",
    "refine_model_for_metadata",
]

