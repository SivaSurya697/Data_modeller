"""Build compact JSON context for a domain."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.models.tables import ChangeSet, DataModel, Domain


@dataclass(slots=True)
class DomainContext:
    """Container for context sent to the language model."""

    domain: Domain
    entities: list[Entity]
    relationships: list[Relationship]
    settings: Setting | None
    changes: list[ChangeSet]

    def to_prompt_sections(self) -> list[str]:
        """Transform the context into textual sections."""

        sections: list[str] = [
            f"Domain: {self.domain.name}\nDescription: {self.domain.description}"
        ]
        if self.settings:
            details = list(
                filter(
                    None,
                    [
                        f"- Base URL: {self.settings.base_url}" if self.settings.base_url else None,
                        f"- Model name: {self.settings.model_name}" if self.settings.model_name else None,
                        "- API key configured" if self.settings.api_key_enc else None,
                    ],
                )
            )
            if not details:
                details = ["- No overrides configured."]
            sections.append("Operational Settings:\n" + "\n".join(details))
        if self.entities:
            entity_lines: list[str] = []
            for entity in self.entities:
                description = entity.description or "No description captured."
                documentation = (entity.documentation or "").strip()
                attribute_lines = [
                    f"  - {attribute.name} ({attribute.data_type or 'unspecified'})"
                    + (f" – {attribute.description}" if attribute.description else "")
                    for attribute in entity.attributes
                ]
                block_parts = [
                    f"Entity: {entity.name}",
                    f"Description: {description}",
                ]
                if documentation:
                    block_parts.append(f"Documentation:\n{documentation}")
                if attribute_lines:
                    block_parts.append("Attributes:\n" + "\n".join(attribute_lines))
                entity_lines.append("\n".join(block_parts))
            sections.append("Existing Entities:\n" + "\n\n".join(entity_lines))
        if self.relationships:
            rel_lines = [
                f"- {rel.from_entity.name} {rel.relationship_type} {rel.to_entity.name}"
                + (f" – {rel.description}" if rel.description else "")
                for rel in self.relationships
            ]
            sections.append("Existing Relationships:\n" + "\n".join(rel_lines))
        if self.changes:
            change_lines: list[str] = []
            for change in self.changes:
                summary = change.title
                if change.description:
                    summary = f"{summary} — {change.description}"
                change_lines.append(
                    f"- {change.created_at:%Y-%m-%d} [{change.state}] {summary}"
                )
            sections.append(f"Recent Changes:\n" + "\n".join(change_lines))
        return sections


def load_context(session: Session, domain_id: int) -> DomainContext:
    """Load all relevant context for a domain."""

    domain = session.execute(
        select(Domain)
        .where(Domain.id == domain_id)
        .options(
            joinedload(Domain.entities).joinedload(Entity.attributes),
            joinedload(Domain.relationships).joinedload(Relationship.from_entity),
            joinedload(Domain.relationships).joinedload(Relationship.to_entity),
        )
    ).scalar_one_or_none()
    if domain is None:
        raise ValueError("Domain not found")

    entities = sorted(domain.entities, key=lambda item: item.name.lower())
    relationships = sorted(
        domain.relationships,
        key=lambda rel: (rel.from_entity.name.lower(), rel.to_entity.name.lower(), rel.relationship_type),
    )
    settings: dict[str, str] = {}
    changes = list(
        session.execute(
            select(ChangeSet)
            .where(ChangeSet.domain_id == domain_id)
            .order_by(ChangeSet.created_at.desc())
        ).scalars()
    )

    return DomainContext(
        domain=domain,
        entities=entities,
        relationships=relationships,
        settings=settings,
        changes=changes,
    )

    return attribute_dict


    sections: list[str] = context.to_prompt_sections()
    if instructions:
        sections.append(f"Additional Instructions:\n{instructions.strip()}")
    sections.append(
        "Respond using JSON with a top-level 'entities' array. Each entity should"
        " include 'name', optional 'description', optional 'documentation', and an"
        " 'attributes' array with 'name', optional 'data_type', optional 'description',"
        " and 'is_nullable'. Include optional 'relationships' linking entity names,"
        " and a 'changes' array of review notes if applicable."
    )
    return "\n\n".join(sections)
