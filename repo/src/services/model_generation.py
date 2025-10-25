"""Higher level helpers orchestrating model drafting flows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.tables import DataModel, Domain
from src.services.llm_modeler import ModelingService
from src.services.settings import AppSettings
from src.services.validators import DraftRequest


@dataclass(slots=True)
class PriorContext:
    """Summary of the prior artefacts for a domain."""

    domain: Domain
    models: list[DataModel]

    def prior_snippets(self) -> list[dict[str, Any]]:
        """Return lightweight snippets describing existing models."""

        snippets: list[dict[str, Any]] = []
        for model in self.models:
            snippets.append(
                {
                    "id": model.id,
                    "name": model.name,
                    "summary": model.summary,
                    "definition": model.definition,
                }
            )
        return snippets

    def source_summary(self) -> str:
        """Build a textual overview of the available source material."""

        lines: list[str] = [
            f"Domain: {self.domain.name}",
            self.domain.description.strip(),
        ]
        if self.models:
            lines.append(f"Existing model count: {len(self.models)}")
        else:
            lines.append("No existing models found for this domain.")
        return "\n".join(line for line in lines if line)


def compact_prior_context(session: Session, domain_name: str) -> PriorContext:
    """Load the minimal prior context required for model drafting."""

    domain = (
        session.execute(select(Domain).where(Domain.name == domain_name))
        .scalar_one_or_none()
    )
    if domain is None:
        raise ValueError(f"Domain '{domain_name}' was not found.")

    models = list(
        session.execute(
            select(DataModel)
            .where(DataModel.domain_id == domain.id)
            .order_by(DataModel.updated_at.desc())
        ).scalars()
    )
    return PriorContext(domain=domain, models=models)


@dataclass(slots=True)
class DraftFreshResult:
    """Structured payload returned to the API after drafting."""

    model_json: dict[str, Any]
    qa: list[dict[str, str]]


def _format_prior_snippets(prior_snippets: Iterable[dict[str, Any]]) -> str:
    """Convert snippets into a small instruction block."""

    lines: list[str] = []
    for snippet in prior_snippets:
        name = str(snippet.get("name") or "Unnamed Model").strip()
        summary = str(snippet.get("summary") or "No summary provided.").strip()
        lines.append(f"- {name}: {summary}")
    return "\n".join(lines)


def draft_fresh(
    *,
    session: Session,
    settings: AppSettings,
    domain: Domain,
    prior_snippets: list[dict[str, Any]],
    source_summary: str,
) -> DraftFreshResult:
    """Draft a brand new model leveraging the available context."""

    service = ModelingService(settings)

    instructions_parts: list[str] = []
    if source_summary:
        instructions_parts.append("Context summary:\n" + source_summary)
    if prior_snippets:
        instructions_parts.append(
            "Relevant prior models:\n" + _format_prior_snippets(prior_snippets)
        )
    instructions = "\n\n".join(instructions_parts) or None

    request = DraftRequest(domain_id=domain.id, instructions=instructions)
    result = service.generate_draft(session, request)

    model = result.model
    model_json: dict[str, Any] = {
        "id": model.id,
        "domain_id": model.domain_id,
        "name": model.name,
        "summary": model.summary,
        "definition": model.definition,
        "instructions": model.instructions,
    }

    qa = [
        {"question": "Impact consideration", "answer": impact}
        for impact in result.impact
    ]
    return DraftFreshResult(model_json=model_json, qa=qa)


def draft_extend(**_: Any) -> dict[str, Any]:
    """Placeholder for future model extension support."""

    raise NotImplementedError("Model extension drafting has not been implemented yet.")
