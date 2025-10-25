"""REST endpoints for model drafting operations."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from src.models.db import session_scope
from src.services.model_generation import (
    compact_prior_context,
    draft_extend,
    draft_fresh,
)
from src.services.settings import load_settings

bp = Blueprint("model", __name__, url_prefix="/api/model")


@bp.post("/draft")
def create_draft() -> ResponseReturnValue:
    """Generate a fresh model draft for the requested domain."""

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


@bp.post("/extend")
def extend_draft() -> ResponseReturnValue:
    """Placeholder endpoint for future model extension flows."""

    payload = request.get_json(silent=True) or {}
    try:
        with session_scope() as session:
            result = draft_extend(session=session, payload=payload)
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)
