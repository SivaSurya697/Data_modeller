import json
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from src.api import model as model_module
from src.models import db as db_module
from src.models.tables import ChangeSet, Domain


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)

    application = create_app()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    application.config.update(TESTING=True, ARTIFACTS_DIR=str(artifacts))
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def session():
    with db_module.session_scope() as session:
        yield session


def _write_artifact(app, domain_name: str, payload: dict[str, object]) -> None:
    artifacts_dir = Path(app.config["ARTIFACTS_DIR"])
    path = artifacts_dir / f"model_{domain_name}_1.0.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_extend_returns_error_when_artifact_missing(client):
    response = client.post("/api/model/extend", json={"domain": "Eligibility"})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False


def test_extend_creates_changeset_and_items(app, client, session, monkeypatch):
    domain = Domain(name="Eligibility", description="Eligibility domain")
    session.add(domain)
    session.commit()

    baseline = {
        "entities": [
            {"name": "Eligibility", "attributes": [{"name": "eligibility_id"}]},
            {"name": "Enrollment", "attributes": [{"name": "enrollment_id"}]},
        ],
        "relationships": [
            {"from": "Enrollment", "to": "Eligibility", "type": "references"}
        ],
    }
    _write_artifact(app, "Eligibility", baseline)

    diff_payload = json.dumps(
        {
            "proposed_changes": [
                {
                    "action": "add_entity",
                    "target": "EligibilityPeriod",
                    "after": {"name": "EligibilityPeriod", "attributes": []},
                    "rationale": "Introduce period tracking",
                },
                {
                    "action": "update_relationship",
                    "target": "Enrollment->Eligibility",
                    "after": {"from": "Enrollment", "to": "Eligibility", "type": "refines"},
                    "rationale": "Clarify relationship",
                },
            ],
            "dictionary_updates": [{"term": "EligibilityPeriod"}],
        }
    )

    monkeypatch.setattr(
        model_module,
        "draft_extend",
        lambda session, **_: diff_payload,
    )

    response = client.post("/api/model/extend", json={"domain": "Eligibility"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["diff"]["proposed_changes"][0]["object_type"] == "entity"
    assert data["diff"]["proposed_changes"][1]["object_type"] == "relationship"

    session.expire_all()
    change_set = session.get(ChangeSet, data["changeset_id"])
    assert change_set is not None
    assert change_set.state == "draft"
    assert len(change_set.items) == 2
    relationship_item = next(item for item in change_set.items if item.object_type == "relationship")
    assert relationship_item.before_json.get("type") == "references"
    assert relationship_item.after_json.get("type") == "refines"


def test_extend_respects_changeset_state(app, client, session, monkeypatch):
    domain = Domain(name="Eligibility", description="Eligibility domain")
    session.add(domain)
    session.flush()
    change_set = ChangeSet(
        domain=domain,
        title="Existing",
        summary="Existing diff",
        state="approved",
        created_by=1,
    )
    session.add(change_set)
    session.commit()

    baseline = {"entities": [], "relationships": []}
    _write_artifact(app, "Eligibility", baseline)

    monkeypatch.setattr(
        model_module,
        "draft_extend",
        lambda session, **_: json.dumps({"proposed_changes": [], "dictionary_updates": []}),
    )

    response = client.post(
        "/api/model/extend",
        json={"domain": "Eligibility", "changeset_id": change_set.id},
    )
    assert response.status_code == 400


def test_extend_returns_error_for_invalid_llm_payload(app, client, session, monkeypatch):
    domain = Domain(name="Eligibility", description="Eligibility domain")
    session.add(domain)
    session.commit()

    _write_artifact(app, "Eligibility", {"entities": []})

    monkeypatch.setattr(model_module, "draft_extend", lambda session, **_: "not-json")

    response = client.post("/api/model/extend", json={"domain": "Eligibility"})
    assert response.status_code == 400
