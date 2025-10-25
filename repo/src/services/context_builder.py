"""Helpers to build context for LLM prompts."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.tables import ChangeSet, DataModel, Domain


@dataclass(slots=True)
class DomainContext:
    """Container for context sent to the language model."""

    domain: Domain
    models: list[DataModel]
    settings: dict[str, str]
    changes: list[ChangeSet]

    def to_prompt_sections(self) -> list[str]:
        """Transform the context into textual sections."""

        sections: list[str] = [
            f"Domain: {self.domain.name}\nDescription: {self.domain.description}"
        ]
        if self.settings:
            setting_lines = "\n".join(
                f"- {key}: {value}" for key, value in sorted(self.settings.items())
            )
            sections.append(f"Operational Settings:\n{setting_lines}")
        if self.models:
            model_lines = []
            for model in self.models:
                model_lines.append(
                    f"Model: {model.name}\nSummary: {model.summary}\nDefinition:\n{model.definition}"
                )
            sections.append("Existing Models:\n" + "\n\n".join(model_lines))
        if self.changes:
            change_lines = "\n".join(
                f"- {change.created_at:%Y-%m-%d}: {change.description}"
                for change in self.changes
            )
            sections.append(f"Recent Changes:\n{change_lines}")
        return sections


def load_context(session: Session, domain_id: int) -> DomainContext:
    """Load all relevant context for a domain."""

    domain = session.get(Domain, domain_id)
    if domain is None:
        raise ValueError("Domain not found")

    models = list(
        session.execute(
            select(DataModel).where(DataModel.domain_id == domain_id).order_by(DataModel.updated_at.desc())
        ).scalars()
    )
    settings: dict[str, str] = {}
    changes = list(
        session.execute(
            select(ChangeSet)
            .join(DataModel)
            .where(DataModel.domain_id == domain_id)
            .order_by(ChangeSet.created_at.desc())
        ).scalars()
    )

    return DomainContext(domain=domain, models=models, settings=settings, changes=changes)


def build_prompt(context: DomainContext, instructions: str | None = None) -> str:
    """Compose the prompt sent to the language model."""

    sections: list[str] = context.to_prompt_sections()
    if instructions:
        sections.append(f"Additional Instructions:\n{instructions.strip()}")
    sections.append(
        "Respond using JSON with keys 'name', 'summary', 'definition' and optional 'changes'."
    )
    return "\n\n".join(sections)
