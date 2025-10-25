"""Helpers for persisting and retrieving encrypted user settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.tables import Settings

DEFAULT_USER_ID = "default"
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_RATE_LIMIT = 60
_ENCRYPTION_KEY_ENV = "SETTINGS_ENCRYPTION_KEY"


@dataclass(slots=True)
class UserSettings:
    """Typed representation of decrypted settings."""

    user_id: str
    openai_api_key: str
    openai_base_url: str = _DEFAULT_BASE_URL
    rate_limit_per_minute: int = _DEFAULT_RATE_LIMIT


def _get_cipher() -> Fernet:
    key = os.getenv(_ENCRYPTION_KEY_ENV)
    if not key:
        raise RuntimeError(
            "SETTINGS_ENCRYPTION_KEY must be configured to persist user settings."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("SETTINGS_ENCRYPTION_KEY is not a valid Fernet key") from exc


def save_user_settings(
    session: Session,
    user_id: str,
    *,
    openai_api_key: str,
    openai_base_url: str | None = None,
    rate_limit_per_minute: int | None = None,
) -> None:
    """Persist settings for a user, encrypting the API key."""

    api_key_clean = openai_api_key.strip()
    if not api_key_clean:
        raise RuntimeError("OpenAI API key cannot be empty.")

    cipher = _get_cipher()
    encrypted_key = cipher.encrypt(api_key_clean.encode("utf-8")).decode("utf-8")
    base_url = (openai_base_url or _DEFAULT_BASE_URL).strip() or _DEFAULT_BASE_URL
    rate_limit = (
        int(rate_limit_per_minute)
        if rate_limit_per_minute is not None
        else _DEFAULT_RATE_LIMIT
    )
    if rate_limit <= 0:
        raise RuntimeError("Rate limit must be a positive integer.")

    existing = session.execute(
        select(Settings).where(Settings.user_id == user_id)
    ).scalar_one_or_none()

    if existing is None:
        session.add(
            Settings(
                user_id=user_id,
                encrypted_openai_api_key=encrypted_key,
                openai_base_url=base_url,
                rate_limit_per_minute=rate_limit,
            )
        )
    else:
        existing.encrypted_openai_api_key = encrypted_key
        existing.openai_base_url = base_url
        existing.rate_limit_per_minute = rate_limit

    session.flush()


def get_user_settings(session: Session, user_id: str) -> UserSettings:
    """Return decrypted settings for ``user_id``."""

    record = session.execute(
        select(Settings).where(Settings.user_id == user_id)
    ).scalar_one_or_none()
    if record is None:
        raise RuntimeError(f"No settings configured for user '{user_id}'.")

    cipher = _get_cipher()
    try:
        api_key = cipher.decrypt(record.encrypted_openai_api_key.encode("utf-8"))
    except InvalidToken as exc:  # pragma: no cover - data corruption guard
        raise RuntimeError("Failed to decrypt stored API key.") from exc

    return UserSettings(
        user_id=record.user_id,
        openai_api_key=api_key.decode("utf-8"),
        openai_base_url=record.openai_base_url,
        rate_limit_per_minute=record.rate_limit_per_minute,
    )


__all__ = [
    "DEFAULT_USER_ID",
    "UserSettings",
    "get_user_settings",
    "save_user_settings",
]

