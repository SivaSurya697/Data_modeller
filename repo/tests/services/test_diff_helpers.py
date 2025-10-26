import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services import diff_helpers


BASELINE = json.dumps(
    {
        "entities": [
            {"name": "Customer", "description": "", "attributes": [{"name": "id"}]},
            {"name": "Order", "description": "", "attributes": [{"name": "order_id"}]},
        ],
        "relationships": [
            {
                "from": "Order",
                "to": "Customer",
                "type": "belongs_to",
            }
        ],
    }
)


def test_extract_entity_by_name_returns_matching_entity():
    entity = diff_helpers.extract_entity_by_name(BASELINE, "Customer")
    assert entity is not None
    assert entity["name"] == "Customer"


def test_extract_entity_by_name_returns_none_for_missing():
    assert diff_helpers.extract_entity_by_name(BASELINE, "Missing") is None


def test_extract_relationship_by_pair_matches_from_and_to():
    relationship = diff_helpers.extract_relationship_by_pair(BASELINE, "Order", "Customer")
    assert relationship is not None
    assert relationship["type"] == "belongs_to"


def test_extract_relationship_by_pair_handles_missing_entries():
    assert diff_helpers.extract_relationship_by_pair(BASELINE, "Customer", "Order") is None
