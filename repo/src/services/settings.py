"""Persistence helpers for user-specific configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.tables import Settings

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_RATE_LIMIT = 60
_ENCRYPTION_KEY_ENV = "SETTINGS_ENCRYPTION_KEY"
DEFAULT_USER_ID = "default"


@dataclass(slots=True)
class UserSettings:
    """Typed representation of decrypted user settings."""

    user_id: str
    openai_api_key: str
    openai_base_url: str = _DEFAULT_BASE_URL
    rate_limit_per_minute: int = _DEFAULT_RATE_LIMIT


def _get_cipher() -> Fernet:
    """Return a configured Fernet cipher used for secrets at rest."""

    key = os.getenv(_ENCRYPTION_KEY_ENV)
    if not key:
        raise RuntimeError(
            "SETTINGS_ENCRYPTION_KEY must be configured to persist user settings."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:  # pragma: no cover - invalid secrets
        raise RuntimeError("SETTINGS_ENCRYPTION_KEY is not a valid Fernet key") from exc


def save_user_settings(
    session: Session,
    user_id: str,
    *,
    openai_api_key: str,
    openai_base_url: str | None = None,
    rate_limit_per_minute: int | None = None,
) -> dict[str, bool]:
    """Persist settings for a given user, encrypting sensitive values."""

    cipher = _get_cipher()
    api_key_clean = openai_api_key.strip()
    if not api_key_clean:
        raise RuntimeError("OpenAI API key cannot be empty.")
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
    return {"ok": True}


def get_user_settings(session: Session, user_id: str) -> UserSettings:
    """Return decrypted settings for the requested user."""

    record = session.execute(
        select(Settings).where(Settings.user_id == user_id)
    ).scalar_one_or_none()
    if record is None:
        raise RuntimeError(f"No settings configured for user '{user_id}'.")

    cipher = _get_cipher()
    try:
        api_key = cipher.decrypt(record.encrypted_openai_api_key.encode("utf-8"))
    except InvalidToken as exc:  # pragma: no cover - data corruption
        raise RuntimeError("Failed to decrypt stored API key.") from exc

    return UserSettings(
        user_id=record.user_id,
        openai_api_key=api_key.decode("utf-8"),
        openai_base_url=record.openai_base_url,
        rate_limit_per_minute=record.rate_limit_per_minute,
    )


def _resolve_setting(
    records: dict[str, str],
    user_id: int,
    *aliases: str,
) -> str | None:
    """Resolve a stored setting taking optional user overrides into account."""

    user_prefix = f"user:{user_id}:"
    lookup_order = [f"{user_prefix}{alias}".lower() for alias in aliases]
    lookup_order.extend(alias.lower() for alias in aliases)
    for key in lookup_order:
        value = records.get(key)
        if value:
            return value.strip()
    return None


def load_openai_credentials(db: Session, user_id: int) -> tuple[str, str]:
    """Load OpenAI credentials, checking persisted overrides before fallbacks."""

    settings = load_settings()
    stored = {
        record.key.strip().lower(): record.value.strip()
        for record in db.execute(select(Setting)).scalars()
    }

    api_key = _resolve_setting(stored, user_id, *OPENAI_API_KEY_KEYS) or settings.openai_api_key
    base_url = _resolve_setting(stored, user_id, *OPENAI_BASE_URL_KEYS) or settings.openai_base_url

    api_key = api_key.strip()
    base_url = base_url.strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    if not base_url:
        base_url = settings.openai_base_url
    return api_key, base_url
