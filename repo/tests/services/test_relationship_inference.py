import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models import db as db_module
from src.models.tables import Domain, Entity, Relationship
from src.services.relationship_inference import RelationshipInferenceService


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)
    db_module.init_engine()
    db_module.create_all()
    with db_module.session_scope() as session:
        yield session


def test_infer_relationship_persists_evidence(session):
    domain = Domain(name="Sales", description="Sales domain")
    orders = Entity(domain=domain, name="Orders", description="")
    customers = Entity(domain=domain, name="Customers", description="")
    session.add_all([domain, orders, customers])
    session.flush()

    service = RelationshipInferenceService(session)
    relationships = service.infer_relationships(
        domain.id,
        [
            {
                "name": "orders",
                "row_count": 120,
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "referenced_source": "customers",
                        "referenced_column": "id",
                        "match_count": 118,
                    }
                ],
            }
        ],
    )

    assert len(relationships) == 1
    relationship = relationships[0]
    assert relationship.inference_status == "pending"
    assert relationship.evidence_json == {
        "source": "orders",
        "column": "customer_id",
        "target": "customers",
        "target_column": "id",
        "row_count": 120,
        "match_count": 118,
        "coverage": pytest.approx(118 / 120, rel=1e-6),
    }

    stored = session.get(Relationship, relationship.id)
    assert stored is relationship


def test_infer_relationship_ignores_missing_entities(session):
    domain = Domain(name="Support", description="Support domain")
    Entity(domain=domain, name="Tickets", description="")
    session.add(domain)
    session.flush()

    service = RelationshipInferenceService(session)
    result = service.infer_relationships(
        domain.id,
        [
            {
                "name": "tickets",
                "row_count": 10,
                "foreign_keys": [
                    {"column": "user_id", "referenced_source": "users", "match_count": 7}
                ],
            }
        ],
    )

    assert result == []
    assert session.query(Relationship).count() == 0
