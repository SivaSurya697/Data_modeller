from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models import db as db_module
from src.models.tables import SourceColumn, SourceSystem, SourceTable
from src.services.source_registry import SourceRegistryService


@pytest.fixture(autouse=True)
def _reset_database(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'service.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)
    db_module.init_engine(database_url)
    db_module.create_all()
    yield


@pytest.fixture
def session():
    with db_module.session_scope() as session:
        yield session


def _service() -> SourceRegistryService:
    return SourceRegistryService(clock=lambda: datetime(2024, 6, 1, tzinfo=timezone.utc))


def test_import_persists_system_tables_and_columns(session):
    service = _service()
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

    system = service.import_source(session, payload)
    session.flush()

    assert isinstance(system, SourceSystem)
    assert system.last_imported_at == datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert len(system.tables) == 1
    table = system.tables[0]
    assert isinstance(table, SourceTable)
    assert table.schema_name == "PUBLIC"
    assert len(table.columns) == 2
    assert {column.name for column in table.columns} == {"ORDER_ID", "STATUS"}


def test_profile_table_generates_statistics(session):
    service = _service()
    payload = {
        "system": {
            "name": "Analytics Warehouse",
            "description": "Demo warehouse",
            "connection_type": "snowflake",
        },
        "tables": [
            {
                "schema_name": "PUBLIC",
                "table_name": "ORDERS",
                "columns": [
                    {"name": "ORDER_ID", "data_type": "NUMBER"},
                    {"name": "STATUS", "data_type": "STRING"},
                ],
            }
        ],
    }
    system = service.import_source(session, payload)
    session.flush()
    table_id = system.tables[0].id

    samples = [
        {"ORDER_ID": 1, "STATUS": "NEW"},
        {"ORDER_ID": 2, "STATUS": "SHIPPED"},
        {"ORDER_ID": 3, "STATUS": "NEW"},
    ]
    table = service.profile_table(session, table_id=table_id, samples=samples, total_rows=100)
    session.flush()
    session.expire_all()

    persisted = session.get(SourceTable, table.id)
    assert persisted is not None
    assert persisted.row_count == 100
    assert persisted.sampled_row_count == 3
    assert persisted.table_statistics["sampled_row_count"] == 3

    order_id = next(col for col in persisted.columns if col.name == "ORDER_ID")
    status = next(col for col in persisted.columns if col.name == "STATUS")

    assert order_id.statistics["total"] == 3
    assert pytest.approx(order_id.statistics["avg"], rel=1e-3) == 2.0
    assert status.statistics["distinct"] == 2
    assert status.statistics.get("mode") == "NEW"


def test_import_removes_missing_tables(session):
    service = _service()
    payload = {
        "system": {
            "name": "Analytics Warehouse",
            "connection_type": "snowflake",
        },
        "tables": [
            {
                "schema_name": "PUBLIC",
                "table_name": "ORDERS",
                "columns": [{"name": "ORDER_ID"}],
            }
        ],
    }
    system = service.import_source(session, payload)
    session.flush()

    updated_payload = {
        "system": {
            "name": "Analytics Warehouse",
            "connection_type": "snowflake",
        },
        "tables": [
            {
                "schema_name": "PUBLIC",
                "table_name": "CUSTOMERS",
                "columns": [{"name": "CUSTOMER_ID"}],
            }
        ],
    }
    service.import_source(session, updated_payload)
    session.flush()
    session.expire_all()

    refreshed = session.get(SourceSystem, system.id)
    assert refreshed is not None
    assert {table.table_name for table in refreshed.tables} == {"CUSTOMERS"}
    assert all(isinstance(column, SourceColumn) for table in refreshed.tables for column in table.columns)
