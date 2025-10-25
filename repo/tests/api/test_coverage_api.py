from __future__ import annotations

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
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def session():
    with db_module.session_scope() as session:
        yield session


def _seed_domain(session):
    domain = Domain(name="Commerce", description="Commerce operations")
    customer = Entity(name="Customer", domain=domain)
    Attribute(name="customer_id", data_type="int", is_nullable=False, entity=customer)
    Attribute(name="email_address", data_type="string", is_nullable=True, entity=customer)
    Attribute(name="vip_flag", data_type="boolean", is_nullable=True, entity=customer)

    invoice = Entity(name="Invoice", domain=domain)
    Attribute(name="invoice_id", data_type="string", is_nullable=False, entity=invoice)

    session.add(domain)
    session.commit()
    return domain


def test_api_returns_coverage_report(client, session):
    domain = _seed_domain(session)

    response = client.post("/api/coverage/analyze", json={"domain_id": domain.id})
    assert response.status_code == 200
    payload = response.get_json()
    assert "Invoice" in payload["entity_collisions"]
    assert "Order" in payload["uncovered_entities"]


def test_api_rejects_missing_domain(client):
    response = client.post("/api/coverage/analyze", json={"domain_id": 999})
    assert response.status_code == 404
    payload = response.get_json()
    assert "Domain not found" in payload["error"]


def test_quality_dashboard_renders_results(client, session):
    domain = _seed_domain(session)

    response = client.get(f"/quality/dashboard?domain_id={domain.id}")
    assert response.status_code == 200
    body = response.data.decode()
    assert "Quality Dashboard" in body
    assert "Invoice" in body
    assert "Order" in body
