from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models import db as db_module
from src.models.tables import Attribute, Domain, Entity
from src.services.coverage_analyzer import CoverageAnalyzer


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'coverage.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)

    db_module.init_engine()
    db_module.create_all()

    with db_module.session_scope() as session:
        yield session


def _seed_domain(session):
    analytics = Domain(name="Analytics", description="Business intelligence")

    customer = Entity(name="Customer", description="Stores customer details", domain=analytics)
    Attribute(name="customer_id", data_type="int", is_nullable=False, entity=customer)
    Attribute(name="email_address", data_type="string", is_nullable=True, entity=customer)
    Attribute(name="vip_flag", data_type="boolean", is_nullable=True, entity=customer)

    invoice = Entity(name="Invoice", description="Billing record", domain=analytics)
    Attribute(name="invoice_id", data_type="string", is_nullable=False, entity=invoice)

    session.add(analytics)
    session.commit()
    return analytics


def test_analyzer_highlights_collisions_and_gaps(session):
    domain = _seed_domain(session)

    analyzer = CoverageAnalyzer()
    report = analyzer.analyze_domain(session, domain.id)

    assert "Customer" in report.entity_overlaps
    assert "Invoice" in report.entity_collisions
    assert "Order" in report.uncovered_entities

    assert "customer_id" in report.attribute_overlaps
    assert "email_address" in report.attribute_overlaps
    assert "vip_flag" in report.attribute_collisions
    assert "invoice_id" in report.attribute_collisions
    assert "order_total" in report.uncovered_attributes
