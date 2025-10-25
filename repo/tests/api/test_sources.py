from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.models import db as db_module
from src.models.tables import SourceSystem, SourceTable


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)

    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_sources_blueprint_registered(app):
    assert "sources_api" in app.blueprints
    assert "sources" not in app.blueprints


@pytest.fixture
def session():
    with db_module.session_scope() as session:
        yield session


def _import_sample(client):
    payload = {
        "sources": [
            {
                "name": "analytics.orders",
                "description": "Order fact table",
                "schema": {
                    "columns": [
                        {"name": "order_id", "data_type": "number"},
                        {"name": "status", "data_type": "string"},
                    ]
                },
                "stats": {"row_count": 120},
                "row_count": 120,
            }
        ]
    }
    response = client.post("/api/sources/import", json=payload)
    assert response.status_code == 200
    return response.get_json()


def test_import_endpoint_persists_metadata(client, session):
    result = _import_sample(client)
    assert result["created"] == 1
    assert result["updated"] == 0
    assert len(result["sources"]) == 1
    session.expire_all()
    system = session.query(SourceSystem).one()
    assert system.name == "default"
    table = session.query(SourceTable).one()
    assert table.schema_name == "analytics"
    assert table.table_name == "orders"
    assert table.schema_definition["columns"][0]["name"] == "order_id"
    assert table.row_count == 120


def test_import_endpoint_is_idempotent(client, session):
    first = _import_sample(client)
    assert first["created"] == 1
    second = _import_sample(client)
    assert second["created"] == 0
    assert second["updated"] == 0
    session.expire_all()
    assert session.query(SourceTable).count() == 1


def test_profile_endpoint_merges_statistics(client, session):
    _import_sample(client)
    payload = {
        "name": "analytics.orders",
        "preview_rows": [
            {"order_id": 1, "status": "NEW"},
            {"order_id": 2, "status": "SHIPPED"},
        ],
        "row_count": 120,
    }
    response = client.post("/api/sources/profile", json=payload)
    assert response.status_code == 200
    data = response.get_json()["source"]
    assert data["row_count"] == 120
    assert data["stats"]["sampled_row_count"] == 2
    assert "columns" in data["stats"]
    status_stats = data["stats"]["columns"]["status"]["statistics"]
    assert status_stats["total"] == 2

    session.expire_all()
    table = session.execute(select(SourceTable)).scalar_one()
    assert table.sampled_row_count == 2
    assert table.table_statistics["row_count"] == 120
    assert "status" in table.table_statistics["columns"]


def test_get_list_and_detail_endpoints(client):
    _import_sample(client)
    list_response = client.get("/api/sources/")
    assert list_response.status_code == 200
    listing = list_response.get_json()
    assert listing["sources"][0]["name"] == "analytics.orders"

    detail_response = client.get("/api/sources/analytics.orders")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()["source"]
    assert detail["schema"]["columns"][1]["name"] == "status"

    missing_response = client.get("/api/sources/unknown")
    assert missing_response.status_code == 404
