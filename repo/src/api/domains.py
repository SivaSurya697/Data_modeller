"""Domain management endpoints."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.models.db import get_db
from src.models.tables import Domain, Entity, PublishedModel, Relationship, ReviewTask
from src.services.impact_cross_domain import identify_impacted_domains
from src.services.publish import PublishService
from src.services.validators import DomainInput

bp = Blueprint("domains", __name__, url_prefix="/domains")


def _load_domains() -> list[Domain]:
    with get_db() as session:
        stmt = (
            select(Domain)
            .options(
                joinedload(Domain.entities).joinedload(Entity.attributes),
                joinedload(Domain.models),
                joinedload(Domain.created_review_tasks).joinedload(ReviewTask.target_domain),
                joinedload(Domain.relationships)
                .joinedload(Relationship.from_entity)
                .joinedload(Entity.attributes),
                joinedload(Domain.relationships)
                .joinedload(Relationship.to_entity)
                .joinedload(Entity.attributes),
                joinedload(Domain.published_models).joinedload(PublishedModel.model),
            )
            .order_by(Domain.name)
        )
        domains = list(session.scalars(stmt).unique())
    return domains


@bp.route("/", methods=["GET", "POST"])
def index():
    """List existing domains and handle creation requests."""

    if request.method == "POST":
        submission = request.get_json(silent=True) or request.form.to_dict()
        try:
            payload = DomainInput(**submission)
        except ValidationError as exc:
            messages = ", ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in exc.errors()
            )
            flash(f"Invalid input: {messages}", "error")
            return redirect(url_for("domains.index"))

        name = payload.name.strip()
        description = payload.description.strip()

        with get_db() as session:
            existing = session.execute(
                select(Domain).where(Domain.name.ilike(name))
            ).scalar_one_or_none()
            if existing:
                flash("Domain already exists.", "error")
            else:
                new_domain = Domain(name=name, description=description)
                session.add(new_domain)
                session.flush()

                existing_domains = (
                    session.execute(
                        select(Domain)
                        .options(joinedload(Domain.entities))
                        .where(Domain.id != new_domain.id)
                    )
                    .scalars()
                    .unique()
                    .all()
                )

                findings = identify_impacted_domains(new_domain, existing_domains)
                for finding in findings:
                    session.add(
                        ReviewTask(
                            source_domain=new_domain,
                            target_domain=finding.target_domain,
                            title=finding.title,
                            details=finding.details,
                        )
                    )

                flash("Domain created.", "success")
        return redirect(url_for("domains.index"))

    domains = _load_domains()
    artifacts_dir = Path(current_app.config["ARTIFACTS_DIR"])
    publish_service = PublishService(artifacts_dir)
    publish_states = {
        domain.id: publish_service.preview(domain).to_dict() for domain in domains
    }
    return render_template(
        "domains.html",
        domains=domains,
        publish_states=publish_states,
    )

