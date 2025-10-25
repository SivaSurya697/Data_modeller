from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.llm_client import LLMClient


def _client_with_response(response: str) -> LLMClient:
    client = object.__new__(LLMClient)

    def _fake_chat_complete(_messages):
        return response

    client._chat_complete = _fake_chat_complete  # type: ignore[attr-defined]
    return client


def test_generate_model_payload_accepts_plain_json():
    client = _client_with_response('{"foo": 1}')

    payload = client.generate_model_payload("Describe the schema")

    assert payload == {"foo": 1}


def test_generate_model_payload_accepts_fenced_json():
    client = _client_with_response("```json\n{\n  \"foo\": 1\n}\n```")

    payload = client.generate_model_payload("Describe the schema")

    assert payload == {"foo": 1}


def test_generate_model_payload_accepts_labeled_json():
    client = _client_with_response("json\n{\n  \"foo\": 1\n}")

    payload = client.generate_model_payload("Describe the schema")

    assert payload == {"foo": 1}


def test_generate_model_payload_rejects_malformed_json():
    client = _client_with_response("```json\nnot json\n```")

    with pytest.raises(RuntimeError, match="not valid JSON"):
        client.generate_model_payload("Describe the schema")
