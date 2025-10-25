from __future__ import annotations

from pathlib import Path
import sys

import pytest

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


@pytest.fixture
def session():
    with db_module.session_scope() as session:
        yield session


def _import_sample(client):
    payload = {
        "system": {
            "name": "Analytics Warehouse",
            "description": "Demo warehouse",
            "connection_type": "snowflake",
            "connection_config": {"account": "acme"},
        },
        "tables": [
            {
                "schema_name": "PUBLIC",
                "table_name": "ORDERS",
                "columns": [
                    {"name": "ORDER_ID", "data_type": "NUMBER", "is_nullable": False},
                    {"name": "STATUS", "data_type": "STRING"},
                ],
            }
        ],
    }
    response = client.post("/api/sources/import", json=payload)
    assert response.status_code == 201
    return response.get_json()


def test_import_endpoint_persists_metadata(client, session):
    result = _import_sample(client)
    assert result["name"] == "Analytics Warehouse"
    session.expire_all()
    system = session.query(SourceSystem).one()
    assert system.connection_type == "snowflake"
    assert len(system.tables) == 1
    assert system.tables[0].table_name == "ORDERS"


def test_profile_endpoint_updates_statistics(client, session):
    imported = _import_sample(client)
    table_id = imported["tables"][0]["id"]
    payload = {
        "table_id": table_id,
        "rows": [
            {"ORDER_ID": 1, "STATUS": "NEW"},
            {"ORDER_ID": 2, "STATUS": "SHIPPED"},
        ],
        "total_rows": 2,
    }
    response = client.post("/api/sources/profile", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["sampled_row_count"] == 2
    assert data["table_statistics"]["sampled_row_count"] == 2
    order_column = next(col for col in data["columns"] if col["name"] == "ORDER_ID")
    assert order_column["statistics"]["total"] == 2

    session.expire_all()
    table = session.get(SourceTable, table_id)
    assert table is not None
    assert table.sampled_row_count == 2
    assert table.columns[0].statistics is not None


def test_list_sources_returns_nested_structure(client):
    _import_sample(client)
    response = client.get("/api/sources/")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert data[0]["tables"][0]["columns"][0]["name"] == "ORDER_ID"


def test_sources_page_renders(client):
    _import_sample(client)
    response = client.get("/sources/")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Source Registry" in html
    assert "ORDERS" in html
