"""Model drafting endpoints."""
from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select

from src.models.db import session_scope
from src.models.tables import Domain, DataModel
from src.services.context_builder import load_context
from src.services.impact import evaluate_model_impact
from src.services.llm_modeler import draft_fresh
from src.services.settings import load_settings
from src.services.validators import DraftRequest

bp = Blueprint("modeler", __name__, url_prefix="/modeler")


def _load_domains() -> list[Domain]:
    with session_scope() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())
    return domains


@bp.route("/", methods=["GET"])
def draft_review() -> str:
    """Render the draft review screen."""

    domains = _load_domains()
    return render_template("draft_review.html", domains=domains, draft=None)


@bp.route("/", methods=["POST"])
def generate_draft() -> str:
    """Generate a model draft using the LLM."""

    try:
        payload = DraftRequest(**request.form)
    except ValidationError as exc:
        flash(f"Invalid input: {exc}", "error")
        return redirect(url_for("modeler.draft_review"))

    settings = load_settings()

    try:
        with session_scope() as session:
            context = load_context(session, payload.domain_id)
            prior_snippets = [
                f"{model.name}\nSummary: {model.summary}\nDefinition:\n{model.definition}"
                for model in context.models
            ]
            source_summaries: list[str] = []
            if context.settings:
                setting_lines = "\n".join(
                    f"{key}: {value}" for key, value in sorted(context.settings.items())
                )
                source_summaries.append(f"Operational Settings\n{setting_lines}")
            if context.changes:
                change_lines = "\n".join(
                    f"{change.created_at:%Y-%m-%d}: {change.description}"
                    for change in context.changes
                )
                source_summaries.append(f"Recent Changes\n{change_lines}")

            response_json = draft_fresh(
                settings,
                request=(
                    f"Draft a refined data model for the {context.domain.name} domain. "
                    "Return JSON with name, summary, definition, and optional changes."
                ),
                domain_summary=context.domain.description or "",
                prior_snippets=prior_snippets,
                source_summaries=source_summaries,
                instructions=payload.instructions,
            )

            try:
                payload_data = json.loads(response_json or "{}")
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise ValueError("Model response was not valid JSON") from exc

            name = str(payload_data.get("name") or f"{context.domain.name} Model")
            summary = str(
                payload_data.get("summary") or "Model summary pending review."
            )
            definition = str(payload_data.get("definition") or "").strip()
            if not definition:
                raise ValueError("Model definition missing from LLM response")

            model = DataModel(
                domain=context.domain,
                name=name.strip(),
                summary=summary.strip(),
                definition=definition,
                instructions=(payload.instructions or "").strip() or None,
            )
            session.add(model)
            session.flush()

            change_hints_raw = payload_data.get("changes")
            if isinstance(change_hints_raw, str):
                change_hints = [change_hints_raw]
            elif isinstance(change_hints_raw, list):
                change_hints = [str(item) for item in change_hints_raw]
            else:
                change_hints = None

            impact = evaluate_model_impact(context.models, model.definition, change_hints)
            draft = {
                "summary": model.summary,
                "definition": model.definition,
                "impact": impact,
            }
    except Exception as exc:
        flash(f"Draft generation failed: {exc}", "error")
        return redirect(url_for("modeler.draft_review"))

    flash("Draft generated successfully.", "success")
    domains = _load_domains()
    return render_template("draft_review.html", domains=domains, draft=draft)
