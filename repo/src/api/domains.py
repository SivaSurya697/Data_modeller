"""Domain management endpoints."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from src.models.db import session_scope
from src.models.tables import Domain

bp = Blueprint("domains", __name__, url_prefix="/api/domains")


def _parse_domain_names(payload: Any) -> list[str]:
    """Extract and validate the list of domain names from the payload."""

    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object.")

    domains = payload.get("domains")
    if not isinstance(domains, list):
        raise ValueError("'domains' must be provided as an array of names.")

    names: list[str] = []
    for item in domains:
        if not isinstance(item, str):
            raise ValueError("All domain entries must be strings.")
        name = item.strip()
        if not name:
            raise ValueError("Domain names cannot be empty.")
        if name not in names:
            names.append(name)

    if not names:
        raise ValueError("At least one domain name must be supplied.")

    return names


@bp.route("/", methods=["GET"])
def list_domains():
    """Return all domains in the system."""

    with session_scope() as session:
        domains = list(session.execute(select(Domain).order_by(Domain.name)).scalars())

    payload = {
        "domains": [
            {
                "id": domain.id,
                "name": domain.name,
                "status": domain.status,
                "version": domain.version,
            }
            for domain in domains
        ]
    }
    return jsonify(payload)


@bp.route("/import", methods=["POST"])
def import_domains():
    """Upsert a list of domains, returning the ones that were created."""

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"ok": False, "error": "Invalid JSON payload."}), 400

    try:
        domain_names = _parse_domain_names(data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    created: list[str] = []
    with session_scope() as session:
        existing_names = set(
            session.execute(
                select(Domain.name).where(Domain.name.in_(domain_names))
            ).scalars()
        )

        for name in domain_names:
            if name in existing_names:
                continue
            session.add(
                Domain(
                    name=name,
                    description="",
                    status="published",
                    version="0.0.0",
                )
            )
            created.append(name)

    return jsonify({"ok": True, "created": created})
