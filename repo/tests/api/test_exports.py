from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.models import db as db_module
from src.models.tables import Attribute, DataModel, Domain, Entity, ExportRecord


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


def test_exports_post_handles_eager_loaded_collections(client, session):
    domain = Domain(name="Analytics", description="Business analytics")
    entity = Entity(name="Report", description="", domain=domain)
    Attribute(name="title", data_type="string", entity=entity)
    Attribute(name="owner", data_type="string", entity=entity)
    DataModel(
        domain=domain,
        version=1,
        name="Analytics Model",
        summary="A model for analytics",
        definition="Definition",
    )
    session.add(domain)
    session.commit()

    response = client.post(
        "/exports/",
        data={"domain_id": str(domain.id), "exporter": "dictionary"},
        follow_redirects=False,
    )

    assert response.status_code == 302

    session.expire_all()
    records = session.query(ExportRecord).all()
    assert len(records) == 1
    export_path = Path(records[0].file_path)
    assert export_path.exists()
    content = export_path.read_text(encoding="utf-8")
    assert "Latest model version: v1" in content
