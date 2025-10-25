"""Wrapper around the OpenAI Chat Completions API."""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from src.services.settings import AppSettings

DEFAULT_MODEL_NAME = "gpt-4o-mini"


class LLMClient:
    """Typed wrapper for invoking the OpenAI client."""

    def __init__(self, settings: AppSettings, model_name: str = DEFAULT_MODEL_NAME) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        self._settings = settings
        self._model_name = model_name
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    def generate_model_payload(self, prompt: str) -> dict[str, Any]:
        """Call the chat completions endpoint and parse the JSON payload."""

        response = self._client.chat.completions.create(
            model=self._model_name,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior data modeller. Provide concise JSON outputs "
                        "containing name, summary, definition (markdown allowed), and "
                        "an optional changes array describing deltas."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        try:
            payload: dict[str, Any] = json.loads(content)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ValueError("Model response was not valid JSON") from exc
        return payload
