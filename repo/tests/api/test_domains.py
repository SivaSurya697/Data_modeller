from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.models import db as db_module
from src.models.tables import Domain, Entity, ReviewTask


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


def test_domain_creation_generates_review_tasks(client, session):
    payments = Domain(name="Payments", description="Handles payment transactions")
    Entity(name="Transaction", description="Financial transaction", domain=payments)
    session.add(payments)
    session.commit()

    response = client.post(
        "/domains/",
        data={
            "name": "Payment Analytics",
            "description": "Analytics for payments and transaction monitoring",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.data.decode()
    assert "Review overlap with Payments" in body
    assert "Impacted domain: Payments" in body

    session.expire_all()
    tasks = session.query(ReviewTask).all()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.source_domain.name == "Payment Analytics"
    assert task.target_domain.name == "Payments"
    assert "payment" in task.details.lower()


def test_domain_creation_without_overlap_does_not_create_tasks(client, session):
    logistics = Domain(name="Logistics", description="Supply chain and warehousing")
    session.add(logistics)
    session.commit()

    response = client.post(
        "/domains/",
        data={
            "name": "Culinary Arts",
            "description": "Recipe development and gastronomy insights",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.data.decode()
    assert "No review tasks generated." in body

    session.expire_all()
    assert session.query(ReviewTask).count() == 0
