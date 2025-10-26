from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.models import db as db_module
from src.models.tables import ChangeItem, ChangeSet, Domain


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


def _create_changeset(session, title: str, state: str = "draft") -> ChangeSet:
    domain = Domain(name=f"Domain {title}", description="Test domain")
    session.add(domain)
    session.flush()
    change_set = ChangeSet(
        domain=domain,
        title=title,
        summary="Summary",
        state=state,
        created_by=1,
    )
    session.add(change_set)
    session.flush()
    change_set.items.append(
        ChangeItem(
            object_type="entity",
            object_id=0,
            action="add_entity",
            target="Example",
            before_json={},
            after_json={"name": "Example"},
            rationale="",
        )
    )
    session.commit()
    return change_set


def test_list_changesets_returns_state(client, session):
    first = _create_changeset(session, "First")
    second = _create_changeset(session, "Second", state="in_review")

    response = client.get("/api/changesets/")
    assert response.status_code == 200
    data = response.get_json()
    states = {item["state"] for item in data}
    assert states == {"draft", "in_review"}


def test_get_changeset_returns_items_json(client, session):
    change_set = _create_changeset(session, "Detail Test")

    response = client.get(
        f"/api/changesets/{change_set.id}", headers={"Accept": "application/json"}
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["id"] == change_set.id
    assert len(payload["items"]) == 1
    assert payload["items"][0]["after_json"]["name"] == "Example"


def test_update_changeset_state_allows_valid_transition(client, session):
    change_set = _create_changeset(session, "State Test")

    response = client.post(
        f"/api/changesets/{change_set.id}/state",
        json={"state": "in_review"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["state"] == "in_review"


def test_update_changeset_state_blocks_invalid_transition(client, session):
    change_set = _create_changeset(session, "Published", state="published")

    response = client.post(
        f"/api/changesets/{change_set.id}/state",
        json={"state": "draft"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
