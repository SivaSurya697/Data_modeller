import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services import model_store


def test_parse_version_handles_valid_and_invalid_values():
    assert model_store.parse_version("1.2") == (1, 2)
    assert model_store.parse_version("0.9") == (0, 9)
    assert model_store.parse_version("invalid") == (0, 0)
    assert model_store.parse_version("1") == (0, 0)


def test_latest_model_path_returns_highest_version(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "model_Sales_1.0.json").write_text("{}", encoding="utf-8")
    (artifacts / "model_Sales_2.1.json").write_text("{}", encoding="utf-8")
    (artifacts / "model_Sales_invalid.json").write_text("{}", encoding="utf-8")

    latest = model_store.latest_model_path(str(artifacts), "Sales")
    assert latest is not None
    assert latest.endswith("model_Sales_2.1.json")


def test_load_latest_model_json_returns_content(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    payload = {"entities": []}
    path = artifacts / "model_Analytics_3.0.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    content = model_store.load_latest_model_json(str(artifacts), "Analytics")
    assert json.loads(content) == payload
