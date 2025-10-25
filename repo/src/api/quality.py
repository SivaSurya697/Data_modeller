"""Views presenting quality metrics such as ontology coverage."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from src.models.db import get_db
from src.models.tables import Domain
from src.services.coverage_analyzer import CoverageAnalyzer

bp = Blueprint("quality", __name__, url_prefix="/quality")


@bp.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    """Render the quality dashboard with ontology coverage metrics."""

    analyzer = CoverageAnalyzer()
    selected_domain_id = request.values.get("domain_id")

    with get_db() as session:
        domains = list(session.scalars(select(Domain).order_by(Domain.name)))
        if not domains:
            flash("No domains available to analyze.", "warning")
            return render_template(
                "quality_dashboard.html",
                domains=domains,
                selected_domain_id=None,
                report=None,
            )

        if selected_domain_id is None:
            selected_domain_id = str(domains[0].id)

        try:
            domain_id = int(selected_domain_id)
        except ValueError:
            flash("Invalid domain selected for analysis.", "error")
            return redirect(url_for("quality.dashboard"))

        try:
            report = analyzer.analyze_domain(session, domain_id)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("quality.dashboard"))

    return render_template(
        "quality_dashboard.html",
        domains=domains,
        selected_domain_id=domain_id,
        report=report,
    )


__all__ = ["bp"]
