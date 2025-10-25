"""API endpoints exposing ontology coverage analysis."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from src.models.db import get_db
from src.services.coverage_analyzer import CoverageAnalyzer
from src.services.validators import CoverageAnalysisRequest

bp = Blueprint("coverage_api", __name__, url_prefix="/api/coverage")


@bp.route("/analyze", methods=["POST"])
def analyze():
    """Analyze a domain's ontology coverage and return the findings."""

    payload = request.get_json(silent=True) or {}
    try:
        data = CoverageAnalysisRequest(**payload)
    except ValidationError as exc:
        return jsonify({"errors": exc.errors()}), 400

    analyzer = CoverageAnalyzer()
    with get_db() as session:
        try:
            report = analyzer.analyze_domain(session, data.domain_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    return jsonify(report.to_dict())


__all__ = ["bp"]
