from pathlib import Path
import sys
from typing import Iterable

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.llm_client import LLMClient


def _client_with_responses(responses: Iterable[str]) -> LLMClient:
    iterator = iter(responses)
    client = object.__new__(LLMClient)

    def _fake_chat_complete(_messages):
        try:
            return next(iterator)
        except StopIteration:  # pragma: no cover - defensive guard
            raise AssertionError("No more stubbed responses available")

    client._chat_complete = _fake_chat_complete  # type: ignore[attr-defined]
    return client


def test_generate_draft_payload_accepts_plain_json():
    client = _client_with_responses(['{"foo": 1}'])

    payload = client.generate_draft_payload([{"role": "user", "content": "Describe"}])

    assert payload == {"foo": 1}


def test_generate_draft_payload_accepts_fenced_json():
    client = _client_with_responses(["```json\n{\n  \"foo\": 1\n}\n```"])

    payload = client.generate_draft_payload([{"role": "user", "content": "Describe"}])

    assert payload == {"foo": 1}


def test_generate_draft_payload_rejects_malformed_json():
    client = _client_with_responses(["```json\nnot json\n```"])

    with pytest.raises(RuntimeError, match="not valid JSON"):
        client.generate_draft_payload([{"role": "user", "content": "Describe"}])


def test_generate_critique_payload_returns_amended_model_when_present():
    critique_response = (
        "{"  #
        "\"issues\": [\"Missing customer relationship\"],"
        " \"amended_model\": {\"summary\": \"Revised\", \"changes\": [\"Added link\"]}}"
    )
    client = _client_with_responses([critique_response])

    critique_payload, amended_payload = client.generate_critique_payload(
        [{"role": "user", "content": "Critique"}]
    )

    assert critique_payload["issues"] == ["Missing customer relationship"]
    assert amended_payload == {"summary": "Revised", "changes": ["Added link"]}


def test_generate_critique_payload_handles_string_amended_model():
    critique_response = (
        "{"  #
        "\"amended_model\": \"{\\\"summary\\\": \\\"Revised\\\"}\"}"
    )
    client = _client_with_responses([critique_response])

    _payload, amended_payload = client.generate_critique_payload(
        [{"role": "user", "content": "Critique"}]
    )

    assert amended_payload == {"summary": "Revised"}
