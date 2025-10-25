import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.models import db as db_module
from src.models.tables import Domain, Entity, Relationship


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
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


def test_infer_relationships_returns_evidence(client, session):
    domain = Domain(name="Sales", description="Sales domain")
    orders = Entity(domain=domain, name="Orders", description="")
    customers = Entity(domain=domain, name="Customers", description="")
    session.add_all([domain, orders, customers])
    session.flush()
    session.commit()

    payload = {
        "domain_id": domain.id,
        "sources": [
            {
                "name": "orders",
                "row_count": 200,
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "referenced_source": "customers",
                        "match_count": 190,
                    }
                ],
            }
        ],
    }

    response = client.post("/api/relationships/infer", json=payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body["relationships"][0]["coverage_percent"] == pytest.approx(95.0)

    relationship_id = body["relationships"][0]["id"]
    with db_module.session_scope() as verify_session:
        stored = verify_session.get(Relationship, relationship_id)
        assert stored is not None
        assert stored.evidence_json["match_count"] == 190
        assert stored.inference_status == "pending"


def test_approve_and_reject_relationship(client, session):
    domain = Domain(name="Analytics", description="Analytics domain")
    events = Entity(domain=domain, name="Events", description="")
    users = Entity(domain=domain, name="Users", description="")
    relationship = Relationship(
        domain=domain,
        from_entity=events,
        to_entity=users,
        relationship_type="inferred_foreign_key",
        inference_status="pending",
        evidence_json={
            "source": "events",
            "column": "user_id",
            "target": "users",
            "target_column": "id",
            "row_count": 10,
            "match_count": 9,
            "coverage": 0.9,
        },
    )
    session.add_all([domain, events, users, relationship])
    session.flush()
    session.commit()

    approve = client.post(f"/api/relationships/{relationship.id}/approve")
    assert approve.status_code == 200
    assert approve.get_json()["inference_status"] == "approved"

    reject = client.post(f"/api/relationships/{relationship.id}/reject")
    assert reject.status_code == 200
    assert reject.get_json()["inference_status"] == "rejected"

    with db_module.session_scope() as verify_session:
        refreshed = verify_session.get(Relationship, relationship.id)
        assert refreshed.inference_status == "rejected"
