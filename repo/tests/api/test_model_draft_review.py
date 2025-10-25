from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.models import db as db_module
from src.models.tables import Domain
from src.services.impact import ImpactItem
from src.services.llm_modeler import DraftResult, ModelingService


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)

    application = create_app()
    application.config.update(
        TESTING=True,
        ARTIFACTS_DIR=str(tmp_path / "artifacts"),
    )
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def session():
    with db_module.session_scope() as session:
        yield session


def test_draft_review_renders_classifications_and_cardinality(client, session, monkeypatch):
    domain = Domain(name="Sales", description="Sales domain")
    session.add(domain)
    session.commit()

    fact = SimpleNamespace(
        name="Sales Fact",
        description="Fact table capturing sales events",
        documentation="Type: Fact",
        attributes=[
            SimpleNamespace(
                name="sale_id",
                data_type="integer",
                is_nullable=False,
                description=None,
            ),
            SimpleNamespace(
                name="amount",
                data_type="decimal",
                is_nullable=True,
                description=None,
            ),
        ],
    )

    dimension = SimpleNamespace(
        name="Product Dimension",
        description="Dimension entity providing product details",
        documentation="Type: Dimension",
        attributes=[
            SimpleNamespace(
                name="product_id",
                data_type="integer",
                is_nullable=True,
                description=None,
            )
        ],
    )

    relationship = SimpleNamespace(
        from_entity=fact,
        to_entity=dimension,
        relationship_type="one-to-many",
        description="Each sale references a product",
    )

    model = SimpleNamespace(domain=domain)
    impact = ImpactItem(
        dimension="model",
        consumer="reviewer",
        impact_level="low",
        explanation="Mock impact",
    )

    draft_result = DraftResult(
        model=model,
        version=2,
        entities=[fact, dimension],
        relationships=[relationship],
        impact=[impact],
    )

    monkeypatch.setattr(ModelingService, "generate_draft", Mock(return_value=draft_result))

    response = client.post(
        "/modeler/draft",
        data={"domain_id": str(domain.id), "instructions": ""},
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "Version 2" in html
    assert "Fact Entities" in html and "Sales Fact" in html
    assert "Dimension Entities" in html and "Product Dimension" in html
    assert "Relationships" in html
    assert "Sales Fact" in html and "Product Dimension" in html
    assert "(1)" in html and "(*)" in html
    assert "one-to-many" in html
    assert "Impact Assessment" in html
