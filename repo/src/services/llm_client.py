"""Wrapper around the OpenAI client with sensible fallbacks."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Mapping, Sequence, Tuple

from openai import (  # type: ignore[import-untyped]
    APIConnectionError,
    APIError,
    APITimeoutError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from src.services.settings import UserSettings

DEFAULT_MODEL_NAME = "gpt-4o-mini"
_LOGGER = logging.getLogger(__name__)
_RECOVERABLE_ERRORS: tuple[type[OpenAIError], ...] = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    APIError,
)


class LLMClient:
    """Thin wrapper around the OpenAI chat completions API."""

    def __init__(self, settings: UserSettings, model_name: str = DEFAULT_MODEL_NAME) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured for this user")
        self._settings = settings
        self._model_name = model_name
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    def generate_draft_payload(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        """Return the initial model payload from the draft prompt."""

        return self._parse_json_payload(self._chat_complete(messages))

    def generate_critique_payload(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> Tuple[Mapping[str, Any], Mapping[str, Any] | None]:
        """Return the critique payload and an amended model when available."""

        payload = self._parse_json_payload(self._chat_complete(messages))

        amended_payload: Mapping[str, Any] | None = None
        amended_raw = payload.get("amended_model")
        if amended_raw is not None:
            amended_payload = self._coerce_mapping(amended_raw)

        return payload, amended_payload

    def json_chat_complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        """Return the parsed JSON payload from an arbitrary chat prompt."""

        return self._parse_json_payload(
            self._chat_complete(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        )

    @staticmethod
    def _sanitize_response(response_text: str) -> str:
        """Return JSON content without code fences or leading labels."""

        text = response_text.strip()

        fence_match = re.fullmatch(
            r"```\s*(?:json)?\s*(?P<body>.*)```",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if fence_match:
            text = fence_match.group("body").strip()
        else:
            if text[:4].lower() == "json" and (len(text) == 4 or text[4].isspace()):
                text = text[4:].lstrip()

        return text

    def _parse_json_payload(self, response_text: str) -> Mapping[str, Any]:
        sanitized_text = self._sanitize_response(response_text)
        try:
            payload = json.loads(sanitized_text)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
            raise RuntimeError("LLM response was not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError("LLM response did not return a JSON object")
        return payload

    def _coerce_mapping(self, value: Any) -> Mapping[str, Any] | None:
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            sanitized_text = self._sanitize_response(value)
            try:
                parsed = json.loads(sanitized_text)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, Mapping):
                return parsed
        return None

    def _chat_complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not messages:
            raise ValueError("messages must not be empty")

        last_exc: OpenAIError | None = None
        for attempt, delay in enumerate((1, 2, 4), start=1):
            try:
                request_kwargs: dict[str, Any] = {
                    "model": self._model_name,
                    "messages": list(messages),
                    "temperature": temperature if temperature is not None else 0.2,
                }
                if max_tokens is not None:
                    request_kwargs["max_tokens"] = max_tokens
                response = self._client.chat.completions.create(**request_kwargs)
                if not response.choices:
                    raise RuntimeError("OpenAI response did not include any choices")
                message = response.choices[0].message
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    return content
                if isinstance(content, Sequence):
                    text = "".join(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, Mapping) and "text" in part
                    )
                    if text:
                        return text
                raise RuntimeError("OpenAI response did not include message content")
            except _RECOVERABLE_ERRORS as exc:
                last_exc = exc
                _LOGGER.warning(
                    "Recoverable OpenAI error during chat completion (attempt %s/3): %s",
                    attempt,
                    exc,
                )
                if attempt == 3:
                    break
                time.sleep(delay)
            except OpenAIError as exc:
                _LOGGER.exception("OpenAI chat completion failed on attempt %s", attempt)
                raise RuntimeError("OpenAI chat completion failed") from exc

        _LOGGER.error(
            "OpenAI chat completion failed after %s attempts",
            3,
            exc_info=last_exc,
        )
        raise RuntimeError("OpenAI chat completion failed after retries") from last_exc


__all__ = ["LLMClient", "DEFAULT_MODEL_NAME"]

