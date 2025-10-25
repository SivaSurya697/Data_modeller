from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models import db as db_module
from src.models.tables import Domain, EntityRole, SCDType
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
    def __init__(
        self,
        draft_payload: dict,
        critique_payload: dict | None = None,
        amended_payload: dict | None = None,
    ):
        self._draft_payload = draft_payload
        self._critique_payload = critique_payload or {}
        self._amended_payload = amended_payload
        self.draft_calls = 0
        self.critique_calls = 0
        self.draft_messages = []
        self.critique_messages = []

    def generate_draft_payload(self, messages):
        self.draft_calls += 1
        self.draft_messages.append(messages)
        return self._draft_payload

    def generate_critique_payload(self, messages):
        self.critique_calls += 1
        self.critique_messages.append(messages)
        return self._critique_payload, self._amended_payload


def test_generate_draft_increments_versions_per_domain(session, monkeypatch):
    payload = {
        "name": "Sales Model",
        "summary": "Latest description",
        "definition": "The detailed definition.",
        "entities": [
            {
                "name": "Customer",
                "description": "Tracks customers",
                "role": "dimension",
                "grain": ["customer_id"],
                "scd_type": "type_2",
                "attributes": [
                    {
                        "name": "customer_id",
                        "data_type": "int",
                        "is_nullable": False,
                        "is_measure": False,
                        "is_surrogate_key": True,
                    },
                    {
                        "name": "email",
                        "data_type": "string",
                        "is_nullable": True,
                        "is_measure": False,
                        "is_surrogate_key": False,
                    },
                ],
            }
        ],
    }

    stub = _StubClient(payload)

    monkeypatch.setattr(llm_modeler, "LLMClient", lambda settings: stub)
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
    assert stub.draft_calls == 3
    assert stub.critique_calls == 3

    customer = next(entity for entity in first.entities if entity.name == "Customer")
    assert customer.role is EntityRole.DIMENSION
    assert customer.scd_type is SCDType.TYPE_2
    assert customer.grain_json == ["customer_id"]
    attr_lookup = {attr.name: attr for attr in customer.attributes}
    assert attr_lookup["customer_id"].is_surrogate_key is True
    assert attr_lookup["customer_id"].is_measure is False
    assert attr_lookup["email"].is_measure is False


def test_generate_draft_applies_amendments_before_persisting(session, monkeypatch):
    draft_payload = {
        "name": "Sales Model",
        "summary": "Initial summary",
        "definition": "Initial definition.",
        "entities": [
            {
                "name": "Sale",
                "role": "fact",
                "attributes": [
                    {"name": "id", "data_type": "int", "is_nullable": False},
                    {"name": "client_id", "data_type": "int", "is_nullable": False},
                ],
            }
        ],
        "changes": ["Initial note"],
    }
    amended_payload = {
        "summary": "Updated summary",
        "definition": "Better definition.",
        "entities": [
            {
                "name": "Sale",
                "role": "fact",
                "grain": ["id"],
                "scd_type": "none",
                "attributes": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_nullable": False,
                        "is_measure": False,
                        "is_surrogate_key": True,
                    },
                    {
                        "name": "client_id",
                        "data_type": "int",
                        "is_nullable": False,
                        "is_measure": False,
                        "is_surrogate_key": False,
                    },
                    {
                        "name": "total",
                        "data_type": "decimal",
                        "is_nullable": False,
                        "is_measure": True,
                        "is_surrogate_key": False,
                    },
                ],
            },
            {
                "name": "Client",
                "role": "dimension",
                "grain": ["client_id"],
                "scd_type": "type_1",
                "attributes": [
                    {
                        "name": "client_id",
                        "data_type": "int",
                        "is_nullable": False,
                        "is_measure": False,
                        "is_surrogate_key": True,
                    },
                    {
                        "name": "email",
                        "data_type": "string",
                        "is_nullable": True,
                        "is_measure": False,
                        "is_surrogate_key": False,
                    },
                ],
            },
        ],
        "relationships": [
            {
                "from": "Sale",
                "to": "Client",
                "type": "references",
                "cardinality_from": "many",
                "cardinality_to": "one",
            }
        ],
    }
    critique_payload = {
        "issues": ["Ensure customer dimension exists"],
        "amendments": {"changes": ["Prioritise Client data"]},
    }
    stub = _StubClient(draft_payload, critique_payload, amended_payload)

    monkeypatch.setattr(llm_modeler, "LLMClient", lambda settings: stub)
    monkeypatch.setattr(
        llm_modeler,
        "get_user_settings",
        lambda _session, _user_id: UserSettings(user_id="tester", openai_api_key="test-key"),
    )

    domain = Domain(name="Sales", description="Sales domain")
    session.add(domain)
    session.flush()

    result = ModelingService().generate_draft(
        session, DraftRequest(domain_id=domain.id)
    )

    assert stub.draft_calls == 1
    assert stub.critique_calls == 1
    entity_names = sorted(entity.name for entity in result.entities)
    assert entity_names == ["Client", "Sale"]
    assert result.model.summary == "Updated summary"
    assert result.model.definition == "Better definition."
    assert any(
        item.explanation == "Prioritise Client data" for item in result.impact
    )
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert relationship.from_entity.name == "Sale"
    assert relationship.to_entity.name == "Client"


def test_generate_draft_requires_metadata(session, monkeypatch):
    payload = {
        "name": "Sales Model",
        "entities": [
            {
                "name": "Order",
                "role": "fact",
                # Missing grain/scd_type/attribute metadata
                "attributes": [
                    {"name": "order_id", "is_nullable": False},
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
    session.add(sales)
    session.flush()

    service = ModelingService()

    with pytest.raises(ValueError):
        service.generate_draft(session, DraftRequest(domain_id=sales.id))


def test_generate_draft_validates_grain_against_attributes(session, monkeypatch):
    payload = {
        "name": "Sales Model",
        "entities": [
            {
                "name": "Order",
                "role": "fact",
                "grain": ["order_id", "missing_col"],
                "scd_type": "none",
                "attributes": [
                    {
                        "name": "order_id",
                        "is_nullable": False,
                        "is_measure": False,
                        "is_surrogate_key": True,
                    },
                    {
                        "name": "total",
                        "is_nullable": False,
                        "is_measure": True,
                        "is_surrogate_key": False,
                    },
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
    session.add(sales)
    session.flush()

    service = ModelingService()

    with pytest.raises(ValueError) as exc:
        service.generate_draft(session, DraftRequest(domain_id=sales.id))

    assert "missing_col" in str(exc.value)

