"""Build prompt context for the modelling service."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.models.tables import (
    ChangeSet,
    Domain,
    Entity,
    Relationship,
    Settings,
)


@dataclass(slots=True)
class DomainContext:
    """Container aggregating the state of a domain."""

    domain: Domain
    entities: list[Entity]
    relationships: list[Relationship]
    settings: Settings | None
    change_sets: list[ChangeSet]

    def to_prompt_sections(self) -> list[str]:
        """Convert the context into human readable prompt sections."""

        sections: list[str] = [
            f"Domain: {self.domain.name}\nDescription: {self.domain.description.strip()}"
        ]

        if self.settings:
            details = [
                f"- Base URL: {self.settings.openai_base_url}",
                f"- Rate limit: {self.settings.rate_limit_per_minute} requests/minute",
            ]
            sections.append("Operational Settings:\n" + "\n".join(details))

        if self.entities:
            entity_blocks: list[str] = []
            for entity in self.entities:
                role_display = getattr(entity, "role", None)
                role_text = (
                    role_display.value
                    if getattr(role_display, "value", None)
                    else str(role_display)
                    if role_display is not None
                    else "unknown"
                )
                scd_display = getattr(entity, "scd_type", None)
                scd_text = (
                    scd_display.value
                    if getattr(scd_display, "value", None)
                    else str(scd_display)
                    if scd_display is not None
                    else "none"
                )
                lines = [
                    f"Entity: {entity.name} (role: {role_text}, SCD: {scd_text})"
                ]
                if entity.description:
                    lines.append(f"Description: {entity.description.strip()}")
                if entity.documentation:
                    lines.append("Documentation:\n" + entity.documentation.strip())
                grain_value = getattr(entity, "grain_json", None)
                if grain_value:
                    if isinstance(grain_value, (list, tuple)):
                        grain_text = ", ".join(str(item) for item in grain_value)
                    else:
                        grain_text = str(grain_value)
                    lines.append(f"Grain: {grain_text}")
                if entity.attributes:
                    attribute_lines = [
                        _format_attribute_line(attribute) for attribute in entity.attributes
                    ]
                    lines.append("Attributes:\n" + "\n".join(attribute_lines))
                entity_blocks.append("\n".join(lines))
            sections.append("Existing Entities:\n" + "\n\n".join(entity_blocks))

        if self.relationships:
            rel_lines = []
            for rel in self.relationships:
                from_card = getattr(rel.cardinality_from, "value", rel.cardinality_from)
                to_card = getattr(rel.cardinality_to, "value", rel.cardinality_to)
                line = (
                    f"- {rel.from_entity.name} ({from_card}) {rel.relationship_type} "
                    f"{rel.to_entity.name} ({to_card})"
                )
                if rel.description:
                    line += f" – {rel.description.strip()}"
                rel_lines.append(line)
            sections.append("Existing Relationships:\n" + "\n".join(rel_lines))

        if self.change_sets:
            change_lines = [
                f"- {change.created_at:%Y-%m-%d} {change.title} — {change.summary}"
                for change in self.change_sets
            ]
            sections.append("Recent Change Sets:\n" + "\n".join(change_lines))

        return sections


def load_context(session: Session, domain_id: int) -> DomainContext:
    """Load the aggregated context for a domain."""

    domain = (
        session.execute(
            select(Domain)
            .where(Domain.id == domain_id)
            .options(
                joinedload(Domain.entities).joinedload(Entity.attributes),
                joinedload(Domain.relationships).joinedload(Relationship.from_entity),
                joinedload(Domain.relationships).joinedload(Relationship.to_entity),
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if domain is None:
        raise ValueError("Domain not found")

    entities = sorted(domain.entities, key=lambda item: item.name.lower())
    relationships = sorted(
        domain.relationships,
        key=lambda rel: (rel.from_entity.name.lower(), rel.to_entity.name.lower(), rel.relationship_type.lower()),
    )

    settings = session.execute(select(Settings).limit(1)).scalar_one_or_none()
    change_sets = list(
        session.execute(
            select(ChangeSet)
            .where(ChangeSet.domain_id == domain.id)
            .order_by(ChangeSet.created_at.desc())
        ).scalars()
    )

    return DomainContext(
        domain=domain,
        entities=entities,
        relationships=relationships,
        settings=settings,
        change_sets=change_sets,
    )


def build_prompt(context: DomainContext, instructions: str | None) -> str:
    """Generate the final prompt sent to the LLM."""

    sections = context.to_prompt_sections()
    if instructions:
        instructions_clean = instructions.strip()
        if instructions_clean:
            sections.append(f"Additional Instructions:\n{instructions_clean}")
    sections.append(
        "Respond with JSON describing the proposed entities. The top-level "
        "object must include an 'entities' array where each entry has 'name', "
        "'role', 'grain', 'scd_type', optional 'description', optional "
        "'documentation', and an 'attributes' array. Each attribute must include "
        "'name', optional 'data_type', optional 'description', 'is_nullable', "
        "'is_measure', 'is_surrogate_key', and optional 'default'. Entity 'role' "
        "must be one of: 'fact', 'dimension', 'bridge', or 'unknown'. 'grain' "
        "must reference attribute names for that entity. 'scd_type' must be one "
        "of: 'none', 'type_0', 'type_1', or 'type_2'. Optionally include a "
        "'relationships' array (with 'from', 'to', 'type', 'cardinality_from', "
        "and 'cardinality_to') and a 'changes' array with impact notes for "
        "reviewers. Relationship cardinalities must each be one of: 'one', "
        "'many', 'zero_or_one', 'zero_or_many', or 'unknown'."
    )
    return "\n\n".join(sections)


__all__ = ["DomainContext", "build_prompt", "load_context"]

def _format_attribute_line(attribute: "Attribute") -> str:
    description = (
        attribute.description.strip() if getattr(attribute, "description", None) else ""
    )
    pieces = [
        f"  - {attribute.name} ({attribute.data_type or 'unspecified'})",
    ]
    if description:
        pieces.append(f" – {description}")
    qualifiers: list[str] = []
    if not attribute.is_nullable:
        qualifiers.append("required")
    if getattr(attribute, "is_measure", False):
        qualifiers.append("measure")
    if getattr(attribute, "is_surrogate_key", False):
        qualifiers.append("surrogate key")
    if qualifiers:
        pieces.append(" [" + ", ".join(qualifiers) + "]")
    default = getattr(attribute, "default_value", None)
    if default:
        pieces.append(f" default={default}")
    return "".join(pieces)


