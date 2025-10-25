"""Wrapper around the OpenAI Chat Completions API."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from openai import OpenAI

from src.services.settings import AppSettings

DEFAULT_MODEL_NAME = "gpt-4o-mini"

ChatMessage = Mapping[str, str]


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

    def chat_complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.1,
        response_format: Mapping[str, Any] | None = None,
    ) -> str:
        """Invoke the chat completions API and return the raw content string."""

        response = self._client.chat.completions.create(
            model=self._model_name,
            temperature=temperature,
            response_format=response_format,
            messages=list(messages),
        )
        return response.choices[0].message.content or ""


def chat_complete(
    settings: AppSettings,
    messages: Sequence[ChatMessage],
    *,
    model_name: str | None = None,
    temperature: float = 0.1,
    response_format: Mapping[str, Any] | None = None,
) -> str:
    """Convenience helper to run a chat completion using the configured settings."""

    client = LLMClient(settings, model_name=model_name or DEFAULT_MODEL_NAME)
    return client.chat_complete(
        messages,
        temperature=temperature,
        response_format=response_format,
    )
