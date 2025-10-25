from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models import db as db_module
from src.models.tables import Domain
from src.services import llm_modeler
from src.services.llm_modeler import ModelingService
from src.services.settings import UserSettings
from src.services.validators import DraftRequest


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'modeler.db'}")
    monkeypatch.setattr(db_module, "_ENGINE", None)
    monkeypatch.setattr(db_module, "_SESSION_FACTORY", None)

    db_module.init_engine()
    db_module.create_all()

    with db_module.session_scope() as session:
        yield session


class _StubClient:
    def __init__(self, payload):
        self._payload = payload

    def generate_model_payload(self, prompt):
        return self._payload


def test_generate_draft_increments_versions_per_domain(session, monkeypatch):
    payload = {
        "name": "Sales Model",
        "summary": "Latest description",
        "definition": "The detailed definition.",
        "entities": [
            {
                "name": "Customer",
                "description": "Tracks customers",
                "attributes": [
                    {"name": "id", "data_type": "int", "is_nullable": False},
                    {"name": "email", "data_type": "string", "is_nullable": True},
                ],
            }
        ],
    }

    monkeypatch.setattr(
        llm_modeler,
        "LLMClient",
        lambda settings: _StubClient(payload),
    )
    monkeypatch.setattr(
        llm_modeler,
        "get_user_settings",
        lambda _session, _user_id: UserSettings(
            user_id="tester", openai_api_key="test-key"
        ),
    )

    sales = Domain(name="Sales", description="Sales domain")
    finance = Domain(name="Finance", description="Finance domain")
    session.add_all([sales, finance])
    session.flush()

    service = ModelingService()

    first = service.generate_draft(session, DraftRequest(domain_id=sales.id))
    second = service.generate_draft(session, DraftRequest(domain_id=sales.id))
    other = service.generate_draft(session, DraftRequest(domain_id=finance.id))

    assert first.version == 1
    assert second.version == 2
    assert other.version == 1

