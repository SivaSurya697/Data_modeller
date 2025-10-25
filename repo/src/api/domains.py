"""Domain management endpoints."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from src.models.db import get_db
from src.models.tables import Domain
from src.services.form_validators import DomainInput

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

    with get_db() as session:
        domains = list(
            session.execute(
                select(Domain)
                .options(joinedload(Domain.entities).joinedload(Entity.attributes))
                .order_by(Domain.name)
            ).scalars()
        )
    return render_template("domains.html", domains=domains)

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

    with get_db() as session:
        existing = session.execute(
            select(Domain).where(Domain.name == name)
        ).scalar_one_or_none()
        if existing:
            flash("Domain already exists.", "error")
            return redirect(url_for("domains.index"))
        domain = Domain(name=name, description=description)
        session.add(domain)
        flash("Domain created.", "success")
    return redirect(url_for("domains.index"))
