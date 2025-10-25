import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models import db as db_module
from src.models.tables import (
    Attribute,
    DataModel,
    Domain,
    Entity,
    EntityRole,
    PublishedModel,
    Relationship,
    RelationshipCardinality,
)
from src.services.publish import PublishBlocked, PublishService


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'publish.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)

    db_module.init_engine()
    db_module.create_all()

    with db_module.session_scope() as session:
        yield session


def _build_ready_domain(session):
    domain = Domain(name="Sales", description="Sales domain")
    session.add(domain)
    session.flush()

    model = DataModel(
        domain=domain,
        version=1,
        name="Sales Warehouse",
        summary="Conformed model for sales analytics",
        definition="Detailed definition",
    )
    session.add(model)

    fact = Entity(
        domain=domain,
        name="Sales Fact",
        description="Captures sales transactions",
        entity_role=EntityRole.FACT,
    )
    fact.attributes.extend(
        [
            Attribute(name="sale_id", data_type="integer", is_nullable=False),
            Attribute(name="amount", data_type="decimal", is_nullable=False),
        ]
    )

    dimension = Entity(
        domain=domain,
        name="Date Dimension",
        description="Calendar attributes",
        entity_role=EntityRole.DIMENSION,
    )
    dimension.attributes.extend(
        [
            Attribute(name="date_key", data_type="integer", is_nullable=False),
            Attribute(name="calendar_date", data_type="date", is_nullable=False),
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


def _build_blocked_domain(session):
    domain = Domain(name="Support", description="Support domain")
    session.add(domain)
    session.flush()

    model = DataModel(
        domain=domain,
        version=1,
        name="Support Model",
        summary="Initial draft",
        definition="Support definition",
    )
    session.add(model)

    fact = Entity(
        domain=domain,
        name="Tickets",
        description="Helpdesk tickets",
        entity_role=EntityRole.FACT,
    )
    fact.attributes.append(Attribute(name="ticket_id", data_type=None, is_nullable=False))
    session.add(fact)
    session.flush()

    return domain


def test_publish_generates_artifacts_and_locks_dimensions(tmp_path, session):
    domain = _build_ready_domain(session)
    artifacts_dir = tmp_path / "artifacts"
    service = PublishService(artifacts_dir)

    preview = service.preview(domain)
    assert preview.is_ready

    result = service.publish(session, domain, version_tag="v1.0.0")

    assert result.version_tag == "v1.0.0"
    for artifact_path in result.artifacts.values():
        assert Path(artifact_path).exists()

    session.refresh(domain)
    locked = [entity for entity in domain.entities if entity.name == "Date Dimension"]
    assert locked and locked[0].is_locked

    publication = session.query(PublishedModel).filter_by(version_tag="v1.0.0").one()
    quality_report = json.loads(publication.quality_report)
    assert all(item["passed"] for item in quality_report)


def test_publish_blocked_when_quality_gates_fail(tmp_path, session):
    domain = _build_blocked_domain(session)
    service = PublishService(tmp_path / "artifacts")

    preview = service.preview(domain)
    assert not preview.is_ready

    with pytest.raises(PublishBlocked) as excinfo:
        service.publish(session, domain)

    assert not excinfo.value.preview.is_ready
    assert any(
        gate["name"] == "Dimension completeness" for gate in excinfo.value.preview.to_dict()["gates"]
    )
