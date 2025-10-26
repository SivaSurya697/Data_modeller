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
from src.services.json_schemas import MODEL_SCHEMA, validate_against_schema


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

SYSTEM_FRESH_TEMPLATE = """
You are a senior healthcare payor data modeller.

REQUIREMENTS (must pass JSON Schema and deterministic validator):
- Each entity has "role": "fact" or "dimension" (use "other" only if unavoidable).
- FACTS MUST include:
   - "grain_json": list of key columns
   - at least one attribute with "is_measure": true
- DIMENSIONS MUST include:
   - "scd_type": one of "none","scd1","scd2"
- Provide keys[], attributes[] with {name, datatype, semantic_type, required, [is_measure], [is_surrogate_key]}.
- Provide relationships[] with type in {"one_to_one","one_to_many","many_to_one","many_to_many"} and a short rule.
- Use snake_case names. Do not mirror raw sources.

OUTPUT:
Return STRICT JSON ONLY with keys: entities, relationships, dictionary, shared_dim_refs.
No markdown, no prose.

JSON SCHEMA (you must conform exactly):
{schema_json_here}
"""

FEWSHOT = """
Example (abbreviated):
{
  "entities": [
    {
      "name": "claim_fact",
      "role": "fact",
      "attributes": [
        {"name":"claim_id","datatype":"string","semantic_type":"ID","required":true},
        {"name":"total_amount","datatype":"decimal","semantic_type":"MONEY","required":true,"is_measure":true}
      ],
      "keys":[{"type":"primary","columns":["claim_id"]}],
      "grain_json": ["claim_id"]
    },
    {
      "name": "beneficiary",
      "role": "dimension",
      "attributes": [
        {"name":"beneficiary_id","datatype":"string","semantic_type":"ID","required":true},
        {"name":"date_of_birth","datatype":"date","semantic_type":"DATE","required":false}
      ],
      "keys":[{"type":"natural","columns":["beneficiary_id"]}],
      "scd_type": "scd1",
      "is_shared_dim": true
    }
  ],
  "relationships": [
    {"from":"claim_fact","to":"beneficiary","type":"many_to_one","rule":"each claim references one beneficiary"}
  ],
  "dictionary": [{"term":"claim","definition":"A submitted request for payment"}],
  "shared_dim_refs": ["beneficiary"]
}
"""

FEWSHOT_EXAMPLES: dict[str, str] = {
    "claims": """
Example (claims-specific):
{
  "entities": [
    {
      "name": "claim_fact",
      "role": "fact",
      "grain_json": ["claim_id"],
      "attributes": [
        {"name":"claim_id","datatype":"string","semantic_type":"ID","required":true},
        {"name":"allowed_amount","datatype":"decimal","semantic_type":"MONEY","required":true,"is_measure":true}
      ],
      "keys":[{"type":"primary","columns":["claim_id"]}]
    },
    {
      "name": "provider_dimension",
      "role": "dimension",
      "scd_type": "scd1",
      "attributes": [
        {"name":"provider_id","datatype":"string","semantic_type":"ID","required":true},
        {"name":"provider_type","datatype":"string","semantic_type":"CATEGORY","required":false}
      ],
      "keys":[{"type":"natural","columns":["provider_id"]}]
    }
  ],
  "relationships": [
    {"from":"claim_fact","to":"provider_dimension","type":"many_to_one","rule":"claims reference a servicing provider"}
  ],
  "dictionary": [],
  "shared_dim_refs": ["provider_dimension"]
}
""",
    "eligibility": """
Example (eligibility-specific):
{
  "entities": [
    {
      "name": "eligibility_fact",
      "role": "fact",
      "grain_json": ["member_id", "effective_date"],
      "attributes": [
        {"name":"member_id","datatype":"string","semantic_type":"ID","required":true},
        {"name":"effective_date","datatype":"date","semantic_type":"DATE","required":true},
        {"name":"premium_amount","datatype":"decimal","semantic_type":"MONEY","required":false,"is_measure":true}
      ],
      "keys":[{"type":"primary","columns":["member_id", "effective_date"]}]
    },
    {
      "name": "plan_dimension",
      "role": "dimension",
      "scd_type": "scd2",
      "attributes": [
        {"name":"plan_id","datatype":"string","semantic_type":"ID","required":true},
        {"name":"plan_name","datatype":"string","semantic_type":"NAME","required":true}
      ],
      "keys":[{"type":"natural","columns":["plan_id"]}]
    }
  ],
  "relationships": [
    {"from":"eligibility_fact","to":"plan_dimension","type":"many_to_one","rule":"eligibility rows reference a plan"}
  ],
  "dictionary": [],
  "shared_dim_refs": ["plan_dimension"]
}
""",
    "provider": """
Example (provider-specific):
{
  "entities": [
    {
      "name": "provider_fact",
      "role": "fact",
      "grain_json": ["provider_id"],
      "attributes": [
        {"name":"provider_id","datatype":"string","semantic_type":"ID","required":true},
        {"name":"encounter_count","datatype":"integer","semantic_type":"COUNT","required":true,"is_measure":true}
      ],
      "keys":[{"type":"primary","columns":["provider_id"]}]
    },
    {
      "name": "provider_profile",
      "role": "dimension",
      "scd_type": "scd1",
      "attributes": [
        {"name":"provider_id","datatype":"string","semantic_type":"ID","required":true},
        {"name":"specialty","datatype":"string","semantic_type":"CATEGORY","required":false}
      ],
      "keys":[{"type":"natural","columns":["provider_id"]}]
    }
  ],
  "relationships": [
    {"from":"provider_fact","to":"provider_profile","type":"many_to_one","rule":"provider aggregates link to provider profiles"}
  ],
  "dictionary": [],
  "shared_dim_refs": ["provider_profile"]
}
""",
}

MAX_AUTOCORRECT_ATTEMPTS = 3

SYSTEM_REFINE = """
You are a modelling reviewer. Fix ONLY metadata gaps without renaming existing fields unless required:
- Add "grain_json" to every FACT if missing; pick keys consistent with attributes and relationships.
- Ensure every FACT has at least one attribute with "is_measure": true (choose appropriate numeric measures).
- Add "scd_type" to every DIMENSION if missing; prefer "scd1" unless historical tracking is evident, then "scd2".
Return STRICT JSON: {"amended_model": <full corrected model>}. No commentary.
"""

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


def prompt_fresh(
    context: DomainContext, instructions: str | None, domain_name: str
) -> list[dict[str, str]]:
    """Build the message list for a fresh draft request."""

    schema_json = json.dumps(MODEL_SCHEMA, indent=2, sort_keys=True)
    system_prompt = SYSTEM_FRESH_TEMPLATE.replace("{schema_json_here}", schema_json)

    system_sections = [system_prompt.strip(), FEWSHOT.strip()]
    domain_lower = domain_name.lower()
    for key, snippet in FEWSHOT_EXAMPLES.items():
        if key in domain_lower:
            system_sections.append(snippet.strip())
    system_message = "\n\n".join(section for section in system_sections if section)

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": _build_fresh_user_prompt(context, instructions)},
    ]
    return messages


def _list_schema_violations(model_obj: dict[str, Any]) -> list[str]:
    """Return human readable schema violations for *model_obj*."""

    _, errors = validate_against_schema(model_obj)
    return list(errors)


def _correction_prompt(violations: list[str], last_model_json: str) -> list[dict[str, str]]:
    """Build a targeted correction prompt for the supplied *violations*."""

    bullet_list = "\n".join(f"- {violation}" for violation in violations)
    user_content = (
        "Violations:\n"
        f"{bullet_list if bullet_list else '- none listed'}\n\n"
        "Previous JSON:\n"
        f"{last_model_json}"
    )
    system_content = (
        "You're correcting the last JSON to satisfy the schema and validator. "
        "Do not add prose; return STRICT JSON. Fix only the missing fields. Preserve all existing names."
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


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
) -> tuple[str, int, list[str], dict[str, Any]]:
    """Generate a fresh model draft with iterative schema corrections."""

    if not domain_name:
        raise ValueError("Domain name must be provided")

    domain_stmt = select(Domain).where(func.lower(Domain.name) == domain_name.lower())
    domain = db.execute(domain_stmt).scalar_one_or_none()
    if domain is None:
        raise ValueError(f"Domain '{domain_name}' was not found")

    context = load_context(db, domain.id)
    instructions_text = instructions if instructions is None else str(instructions)

    user_identifier = str(user_id)
    settings = get_user_settings(db, user_identifier)
    client = LLMClient(settings)

    context_used = {
        "domain_id": context.domain.id,
        "domain_name": context.domain.name,
        "domain_description": context.domain.description,
        "existing_entity_count": len(context.entities),
        "existing_relationship_count": len(context.relationships),
        "change_set_count": len(context.change_sets),
        "instructions_supplied": bool(instructions_text and instructions_text.strip()),
    }

    messages = prompt_fresh(context, instructions_text, domain.name)

    last_violations: list[str] = []
    last_model_json = ""

    for attempt in range(1, MAX_AUTOCORRECT_ATTEMPTS + 1):
        if attempt == 1:
            prompt_messages = messages
        else:
            prompt_messages = _correction_prompt(last_violations, last_model_json)

        payload_raw = client.json_chat_complete(
            prompt_messages, temperature=0.0, top_p=0.0, max_tokens=3500
        )
        if not isinstance(payload_raw, Mapping):
            raise RuntimeError("LLM response did not return a JSON object")

        payload = dict(payload_raw)
        payload.setdefault("entities", [])
        payload.setdefault("relationships", [])
        payload.setdefault("dictionary", [])
        payload.setdefault("shared_dim_refs", [])

        model_json_str = json.dumps(payload, ensure_ascii=False)
        entity_count = (
            len(payload.get("entities", []))
            if isinstance(payload.get("entities"), list)
            else 0
        )
        _LOGGER.info(
            "Draft fresh attempt=%s length=%s entities=%s",
            attempt,
            len(model_json_str),
            entity_count,
        )

        schema_errors = _list_schema_violations(payload)
        validation = validators.validate_model_json(model_json_str)
        validator_issues = (
            [str(item) for item in validation.get("issues", []) if str(item).strip()]
            if isinstance(validation, Mapping)
            else []
        )

        if validation.get("ok", False) and not schema_errors:
            violations_fixed = last_violations if attempt > 1 else []
            return model_json_str, attempt, violations_fixed, context_used

        violations = [*schema_errors]
        if not validation.get("ok", False):
            violations.extend(validator_issues)

        last_violations = violations
        last_model_json = model_json_str

        if attempt >= MAX_AUTOCORRECT_ATTEMPTS:
            error = RuntimeError(
                f"Draft failed after {attempt} correction attempts"
            )
            error.violations = list(violations)
            error.model_json = model_json_str
            error.context_used = context_used
            error.autocorrect_attempts = attempt
            raise error

    # This should be unreachable because the loop either returns or raises.
    raise RuntimeError("Draft generation terminated unexpectedly")


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

