from __future__ import annotations

import json

import pytest

from src.services.coverage_analyzer import (
    analyze_mece,
    find_collisions,
    naming_suggestions,
    parse_model,
    uncovered_terms,
)


@pytest.fixture()
def sample_model_json() -> str:
    model = {
        "entities": [
            {
                "name": "Beneficiary",
                "attributes": [
                    {"name": "member_id"},
                    {"name": "dob"},
                    {"name": "gender"},
                ],
            },
            {
                "name": "Provider",
                "attributes": [
                    {"name": "provider_id"},
                    {"name": "provider_name"},
                    {"name": "specialty"},
                ],
            },
            {
                "name": "Claim",
                "attributes": [
                    {"name": "claim_identifier"},
                    {"name": "service_date"},
                ],
            },
        ]
    }
    return json.dumps(model)


def test_parse_model_validates_payload(sample_model_json):
    model = parse_model(sample_model_json)
    assert isinstance(model, dict)
    assert len(model["entities"]) == 3


def test_parse_model_rejects_invalid_json():
    with pytest.raises(ValueError):
        parse_model("not-json")


def test_find_collisions_detects_similar_attributes(sample_model_json):
    model = parse_model(sample_model_json)
    model["entities"].append(
        {
            "name": "Remittance",
            "attributes": [
                {"name": "claim identifier"},
                {"name": "payment_amount"},
            ],
        }
    )
    collisions = find_collisions(model, threshold=0.85)
    assert collisions
    assert any("Remittance" in entry["entities"] for entry in collisions)


def test_uncovered_terms_reports_missing_entities(sample_model_json):
    model = parse_model(sample_model_json)
    missing = uncovered_terms(model)
    assert any(item["entity"] == "scheme" for item in missing)


def test_naming_suggestions_surface_preferred_names(sample_model_json):
    model = parse_model(sample_model_json)
    suggestions = naming_suggestions(model)
    assert {item["to"] for item in suggestions} >= {"beneficiary_id", "date_of_birth"}


def test_analyze_mece_returns_expected_shape(sample_model_json):
    analysis = analyze_mece(sample_model_json)
    assert set(analysis.keys()) == {
        "collisions",
        "uncovered_terms",
        "naming_suggestions",
        "mece_score",
    }
    assert 0.0 <= analysis["mece_score"] <= 1.0
