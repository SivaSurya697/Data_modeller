"""High level modelling workflow using OpenAI."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.models.tables import DataModel
from src.services.context_builder import build_prompt, load_context
from src.services.impact import evaluate_model_impact
from src.services.llm_client import LLMClient
from src.services.settings import DEFAULT_USER_ID, get_user_settings
from src.services.validators import DraftRequest


@dataclass(slots=True)
class DraftResult:
    """Structured response returned to the API layer."""

    model: DataModel
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

        name = str(payload.get("name") or f"{context.domain.name} Model")
        summary = str(payload.get("summary") or "Model summary pending review.")
        definition = str(payload.get("definition") or "")
        if not definition:
            raise ValueError("Model definition missing from LLM response")

        model = DataModel(
            domain=context.domain,
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

        impact = evaluate_model_impact(context.models, model.definition, change_hints)

        return DraftResult(model=model, impact=impact)
