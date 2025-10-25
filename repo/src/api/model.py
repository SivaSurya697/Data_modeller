"""REST endpoints for model drafting operations."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from src.models.db import get_db
from src.models.tables import Domain
from src.services.llm_modeler import ModelingService
from src.services.validators import DraftRequest

bp = Blueprint("model", __name__, url_prefix="/api/model")


def _load_domains() -> list[Domain]:
    with get_db() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())
    return domains

    payload = request.get_json(silent=True) or {}
    raw_domain = payload.get("domain")
    if not isinstance(raw_domain, str) or not raw_domain.strip():
        return jsonify({"error": "Field 'domain' is required."}), 400

    domain_name = raw_domain.strip()
    settings = load_settings()

    try:
        with session_scope() as session:
            context = compact_prior_context(session, domain_name)
            prior_snippets = context.prior_snippets()
            source_summary = context.source_summary()

            draft_result = draft_fresh(
                session=session,
                settings=settings,
                domain=context.domain,
                prior_snippets=prior_snippets,
                source_summary=source_summary,
            )

        response_body: dict[str, Any] = {
            "model_json": draft_result.model_json,
            "qa": draft_result.qa,
            "context_used": {
                "prior_snippets": prior_snippets,
                "source_summary": source_summary,
            },
        }
        return jsonify(response_body)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - unexpected failures logged
        current_app.logger.exception("Model draft generation failed", exc_info=exc)
        return jsonify({"error": str(exc)}), 400


    service = ModelingService()

    payload = request.get_json(silent=True) or {}
    try:
        with get_db() as session:
            result = service.generate_draft(session, payload)
            draft = {
                "entities": result.entities,
                "impact": result.impact,
            }
    except Exception as exc:
        flash(f"Draft generation failed: {exc}", "error")
        return redirect(url_for("modeler.draft_review"))

    flash("Draft generated successfully.", "success")
    domains = _load_domains()
    return render_template("draft_review.html", domains=domains, draft=draft)
