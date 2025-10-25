from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models.tables import Attribute, DataModel, Domain, Entity, Relationship
from src.services.exporters.plantuml import export_plantuml


@pytest.mark.parametrize("relationship_type, expected", [("one-to-many", '"1" --> "*"'), ("many-to-one", '"*" --> "1"')])
def test_export_plantuml_includes_cardinalities(tmp_path, relationship_type, expected):
    domain = Domain(name="Commerce", description="Retail analytics")

    fact = Entity(name="Order Fact", description="Fact table for orders", domain=domain)
    Attribute(name="order_id", data_type="integer", is_nullable=False, entity=fact)
    Attribute(name="total_amount", data_type="decimal", entity=fact)

    dimension = Entity(name="Customer Dimension", description="Dimension entity", domain=domain)
    Attribute(name="customer_id", data_type="integer", entity=dimension)

    Relationship(
        domain=domain,
        from_entity=fact,
        to_entity=dimension,
        relationship_type=relationship_type,
    )

    DataModel(domain=domain, name="Commerce Model v1", summary="s", definition="d")
    DataModel(domain=domain, name="Commerce Model v2", summary="s", definition="d")

    path = export_plantuml(domain, tmp_path)
    contents = path.read_text(encoding="utf-8")

    assert 'title Commerce (v2)' in contents
    assert 'package "Facts"' in contents
    assert '<<Fact>>' in contents
    assert 'package "Dimensions"' in contents
    assert '<<Dimension>>' in contents
    assert expected in contents
