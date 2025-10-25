"""High level modelling workflow using OpenAI."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.tables import DataModel, Domain
from src.services.context_builder import compact_prior_context
from src.services.impact import evaluate_model_impact
from src.services.llm_client import LLMClient
from src.services.settings import AppSettings
from src.services.validators import DraftRequest


@dataclass(slots=True)
class DraftResult:
    """Structured response returned to the API layer."""

    model: DataModel
    impact: list[str]


class ModelingService:
    """Coordinates prompt building, LLM invocation and persistence."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def generate_draft(self, session: Session, request: DraftRequest) -> DraftResult:
        """Create and persist a model draft for the provided domain."""

        domain = session.get(Domain, request.domain_id)
        if domain is None:
            raise ValueError("Domain not found")

        existing_models = list(
            session.execute(
                select(DataModel)
                .where(DataModel.domain_id == domain.id)
                .order_by(DataModel.updated_at.desc())
            ).scalars()
        )

        prior_context = compact_prior_context(session, domain.name)
        prompt_parts: list[str] = [
            "You are a senior data modeller helping design conceptual data models.",
            f"Prior domain context (JSON):\n{prior_context}",
        ]
        if request.instructions:
            prompt_parts.append(f"User instructions:\n{request.instructions.strip()}")
        prompt_parts.append(
            "Respond using JSON with keys 'name', 'summary', 'definition' and optional 'changes'."
        )
        prompt = "\n\n".join(part for part in prompt_parts if part)

        client = LLMClient(self._settings)
        payload = client.generate_model_payload(prompt)

        name = str(payload.get("name") or f"{domain.name} Model")
        summary = str(payload.get("summary") or "Model summary pending review.")
        definition = str(payload.get("definition") or "")
        if not definition:
            raise ValueError("Model definition missing from LLM response")

        model = DataModel(
            domain=domain,
            name=name.strip(),
            summary=summary.strip(),
            definition=definition.strip(),
            instructions=(request.instructions or "").strip() or None,
        )
        session.add(model)
        session.flush()

        change_hints_raw = payload.get("changes")
        if isinstance(change_hints_raw, str):
            change_hints = [change_hints_raw]
        elif isinstance(change_hints_raw, list):
            change_hints = [str(item) for item in change_hints_raw]
        else:
            change_hints = None

        impact = evaluate_model_impact(existing_models, model.definition, change_hints)

        return DraftResult(model=model, impact=impact)
