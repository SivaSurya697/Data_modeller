from __future__ import annotations

import pytest
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models.tables import Domain, EntityRole, RelationshipCardinality
from src.services.llm_modeler import ModelingService


@pytest.fixture
def service() -> ModelingService:
    return ModelingService()


@pytest.fixture
def domain() -> Domain:
    return Domain(name="Sales", description="Sales analytics")


def test_build_entities_requires_role(service: ModelingService, domain: Domain) -> None:
    payload = {"entities": [{"name": "Order"}]}

    with pytest.raises(ValueError, match="role"):
        service._build_entities(domain, payload)


def test_build_entities_persists_role(service: ModelingService, domain: Domain) -> None:
    payload = {"entities": [{"name": "Order", "role": "fact"}]}

    entities = service._build_entities(domain, payload)

    assert len(entities) == 1
    assert entities[0].entity_role is EntityRole.FACT


def test_build_relationships_requires_cardinality(service: ModelingService, domain: Domain) -> None:
    payload = {
        "entities": [
            {"name": "Order", "role": "fact"},
            {"name": "Customer", "role": "dimension"},
        ],
        "relationships": [
            {"from": "Order", "to": "Customer", "type": "references"}
        ],
    }
    entities = service._build_entities(domain, payload)

    with pytest.raises(ValueError, match="cardinality_from"):
        service._build_relationships(domain, entities, payload)


def test_build_relationships_persists_cardinality(service: ModelingService, domain: Domain) -> None:
    payload = {
        "entities": [
            {"name": "Order", "role": "fact"},
            {"name": "Customer", "role": "dimension"},
        ],
        "relationships": [
            {
                "from": "Order",
                "to": "Customer",
                "type": "references",
                "cardinality_from": "many",
                "cardinality_to": "one",
            }
        ],
    }
    entities = service._build_entities(domain, payload)

    relationships = service._build_relationships(domain, entities, payload)

    assert len(relationships) == 1
    relationship = relationships[0]
    assert relationship.cardinality_from is RelationshipCardinality.MANY
    assert relationship.cardinality_to is RelationshipCardinality.ONE
