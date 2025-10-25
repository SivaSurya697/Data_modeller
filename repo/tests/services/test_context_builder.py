from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models.tables import Attribute, Domain, Entity, EntityRole, SCDType
from src.services.context_builder import DomainContext, build_prompt


def test_prompt_includes_grain_measure_and_scd_requirements():
    domain = Domain(name="Sales", description="Sales domain")
    entity = Entity(
        name="Order",
        role=EntityRole.FACT,
        grain_json=["order_id"],
        scd_type=SCDType.NONE,
    )
    attribute = Attribute(
        name="order_id",
        is_nullable=False,
        is_measure=False,
        is_surrogate_key=True,
    )
    entity.attributes.append(attribute)
    entity.domain = domain

    context = DomainContext(
        domain=domain,
        entities=[entity],
        relationships=[],
        settings=None,
        change_sets=[],
    )

    prompt = build_prompt(context, instructions=None)

    assert "Grain: order_id" in prompt
    assert "'grain'" in prompt
    assert "'is_measure'" in prompt
    assert "'scd_type'" in prompt
