import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.models import db as db_module
from src.models.tables import (
    Attribute,
    DataModel,
    Domain,
    Entity,
    EntityRole,
    Relationship,
    RelationshipCardinality,
)


def _create_ready_domain(session):
    domain = Domain(name="Finance", description="Finance analytics")
    session.add(domain)
    session.flush()

    model = DataModel(
        domain=domain,
        version=1,
        name="Finance Warehouse",
        summary="Finance model",
        definition="Definition",
    )
    session.add(model)

    fact = Entity(
        domain=domain,
        name="Ledger Fact",
        description="Ledger entries",
        entity_role=EntityRole.FACT,
    )
    fact.attributes.extend(
        [
            Attribute(name="entry_id", data_type="integer", is_nullable=False),
            Attribute(name="amount", data_type="decimal", is_nullable=False),
        ]
    )

    dimension = Entity(
        domain=domain,
        name="Account Dimension",
        description="Chart of accounts",
        entity_role=EntityRole.DIMENSION,
    )
    dimension.attributes.extend(
        [
            Attribute(name="account_id", data_type="integer", is_nullable=False),
            Attribute(name="account_name", data_type="text", is_nullable=False),
        ]
    )

    session.add_all([fact, dimension])
    session.flush()

    relationship = Relationship(
        domain=domain,
        from_entity=fact,
        to_entity=dimension,
        relationship_type="many-to-one",
        cardinality_from=RelationshipCardinality.MANY,
        cardinality_to=RelationshipCardinality.ONE,
    )
    session.add(relationship)
    session.flush()

    return domain


def _create_blocked_domain(session):
    domain = Domain(name="HR", description="Human resources")
    session.add(domain)
    session.flush()

    model = DataModel(
        domain=domain,
        version=1,
        name="HR Model",
        summary="HR summary",
        definition="HR definition",
    )
    session.add(model)

    fact = Entity(
        domain=domain,
        name="Employees",
        description="Employee roster",
        entity_role=EntityRole.FACT,
    )
    fact.attributes.append(Attribute(name="employee_id", data_type="integer", is_nullable=False))
    session.add(fact)
    session.flush()

    return domain


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'publish_api.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)

    application = create_app()
    application.config.update(TESTING=True, ARTIFACTS_DIR=str(tmp_path / "artifacts"))
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def test_publish_endpoint_success(client):
    with db_module.session_scope() as session:
        domain = _create_ready_domain(session)
        domain_id = domain.id

    response = client.post(
        "/api/model/publish",
        json={"domain_id": domain_id, "version_tag": "v2024.1"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["version_tag"] == "v2024.1"
    for path in payload["artifacts"].values():
        assert Path(path).exists()

    with db_module.session_scope() as session:
        domain = session.get(Domain, domain_id)
        assert any(entity.is_locked for entity in domain.entities if entity.entity_role == EntityRole.DIMENSION)
        assert domain.published_models
        assert domain.published_models[0].version_tag == "v2024.1"


def test_publish_endpoint_blocks_on_failures(client):
    with db_module.session_scope() as session:
        domain = _create_blocked_domain(session)
        domain_id = domain.id

    response = client.post("/api/model/publish", json={"domain_id": domain_id})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["message"].startswith("Publication blocked")
    assert payload["preview"]["gates"]


def test_publish_endpoint_missing_domain(client):
    response = client.post("/api/model/publish", json={"domain_id": 9999})
    assert response.status_code == 404
