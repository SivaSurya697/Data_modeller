from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.models import db as db_module
from src.models.tables import Attribute, Domain, Entity


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'coverage_api.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)

    application = create_app()
    application.config.update(TESTING=True, ARTIFACTS_DIR=str(tmp_path / "artifacts"))
    Path(application.config["ARTIFACTS_DIR"]).mkdir(parents=True, exist_ok=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def session():
    with db_module.session_scope() as session:
        yield session


def _seed_domain(session):
    domain = Domain(name="Claims", description="Claims domain")
    beneficiary = Entity(name="Beneficiary", domain=domain)
    Attribute(name="member_id", data_type="string", is_nullable=False, entity=beneficiary)
    Attribute(name="dob", data_type="date", is_nullable=False, entity=beneficiary)

    claim = Entity(name="Claim", domain=domain)
    Attribute(name="claim_identifier", data_type="string", is_nullable=False, entity=claim)
    Attribute(name="service_date", data_type="date", is_nullable=False, entity=claim)

    session.add(domain)
    session.commit()
    return domain


def _sample_model_json() -> str:
    return json.dumps(
        {
            "entities": [
                {
                    "name": "Beneficiary",
                    "attributes": [
                        {"name": "member_id"},
                        {"name": "dob"},
                    ],
                },
                {
                    "name": "Provider",
                    "attributes": [
                        {"name": "npi"},
                        {"name": "specialty"},
                    ],
                },
            ]
        }
    )


def test_api_returns_analysis_for_inline_model(client):
    response = client.post("/api/coverage/analyze", json={"model_json": _sample_model_json()})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "analysis" in payload
    assert "mece_score" in payload["analysis"]


def test_api_loads_latest_published_model(client, app):
    artifacts_dir = Path(app.config["ARTIFACTS_DIR"])
    model_path = artifacts_dir / "model_Claims_1.0.json"
    model_path.write_text(_sample_model_json(), encoding="utf-8")

    response = client.post("/api/coverage/analyze", json={"domain": "Claims"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["analysis"]["uncovered_terms"]


def test_api_returns_404_when_domain_missing(client):
    response = client.post("/api/coverage/analyze", json={"domain": "Unknown"})
    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False


def test_quality_dashboard_renders_results(client, session):
    domain = _seed_domain(session)

    response = client.get(f"/quality/dashboard?domain_id={domain.id}")
    assert response.status_code == 200
    body = response.data.decode()
    assert "MECE Coverage" in body
    assert "MECE Score" in body
