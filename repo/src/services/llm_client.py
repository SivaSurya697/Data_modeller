"""Utilities for interacting with the OpenAI Chat Completions API."""
from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)
from sqlalchemy.orm import Session

from src.services.settings import load_openai_credentials

DEFAULT_MODEL_NAME = "gpt-4o-mini"
_LOGGER = logging.getLogger(__name__)
_RECOVERABLE_ERRORS: tuple[type[OpenAIError], ...] = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    APIError,
)


def get_openai_client(db: Session, user_id: int) -> OpenAI:
    """Instantiate an OpenAI client for the provided database session."""

    api_key, base_url = load_openai_credentials(db, user_id)
    return OpenAI(api_key=api_key, base_url=base_url)


def _normalise_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalise chat messages into a list of plain dictionaries."""

    return [dict(message) for message in messages]


def _coerce_content(content: Any) -> str:
    """Coerce message content into a string."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, Mapping) and "text" in part
        )
        if text:
            return text
    raise RuntimeError("OpenAI response did not include message content")


def chat_complete(
    db: Session,
    user_id: int,
    messages: Sequence[Mapping[str, Any]],
    *,
    model: str = DEFAULT_MODEL_NAME,
    **kwargs: Any,
) -> str:
    """Execute a chat completion request with retry semantics."""

    if not messages:
        raise ValueError("messages must not be empty")

    client = get_openai_client(db, user_id)
    last_exc: OpenAIError | None = None

    for attempt, delay in enumerate((1, 2, 4), start=1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=_normalise_messages(messages),
                **kwargs,
            )
            if not response.choices:
                raise RuntimeError("OpenAI response did not include any choices")
            message = response.choices[0].message
            content = _coerce_content(message.content)
            return content
        except _RECOVERABLE_ERRORS as exc:
            last_exc = exc
            _LOGGER.warning(
                "Recoverable OpenAI error during chat completion (attempt %s/3) for user %s: %s",
                attempt,
                user_id,
                exc,
            )
            if attempt == 3:
                break
            time.sleep(delay)
        except OpenAIError as exc:
            _LOGGER.exception(
                "OpenAI chat completion failed for user %s on attempt %s",
                user_id,
                attempt,
            )
            raise RuntimeError("OpenAI chat completion failed") from exc

    _LOGGER.error(
        "OpenAI chat completion failed after %s attempts for user %s",
        3,
        user_id,
        exc_info=last_exc,
    )
    raise RuntimeError("OpenAI chat completion failed after 3 attempts") from last_exc
