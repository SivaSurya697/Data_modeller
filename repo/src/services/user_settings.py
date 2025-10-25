"""Helpers for persisting and retrieving user specific settings."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from src.models.db import session_scope
from src.models.tables import Setting
from src.services.settings import load_settings

_USER_SETTING_FIELDS = {
    "openai_api_key": "OPENAI_API_KEY",
    "openai_base_url": "OPENAI_BASE_URL",
}


def _fetch_settings(keys: Iterable[str]) -> dict[str, str]:
    """Return a mapping of database keys to values for the requested keys."""

    with session_scope() as session:
        rows = session.execute(
            select(Setting).where(Setting.key.in_(list(keys)))
        ).scalars()
        return {row.key: row.value for row in rows}


def save_user_settings(
    *, openai_api_key: str | None = None, openai_base_url: str | None = None
) -> dict[str, str]:
    """Persist provided user settings and return the current values."""

    updates = {
        "openai_api_key": openai_api_key,
        "openai_base_url": openai_base_url,
    }
    filtered_updates = {
        field: value for field, value in updates.items() if value is not None
    }

    if filtered_updates:
        with session_scope() as session:
            for field, value in filtered_updates.items():
                db_key = _USER_SETTING_FIELDS[field]
                existing = session.execute(
                    select(Setting).where(Setting.key == db_key)
                ).scalar_one_or_none()
                if existing:
                    existing.value = value
                else:
                    session.add(Setting(key=db_key, value=value))

    return get_user_settings()


def get_user_settings(*, include_api_key: bool = True) -> dict[str, str]:
    """Return stored user settings, optionally including sensitive values."""

    db_values = _fetch_settings(_USER_SETTING_FIELDS.values())
    result: dict[str, str] = {}
    for field, db_key in _USER_SETTING_FIELDS.items():
        value = db_values.get(db_key)
        if value is not None:
            result[field] = value

    defaults = load_settings()
    if "openai_base_url" not in result and defaults.openai_base_url:
        result["openai_base_url"] = defaults.openai_base_url
    if include_api_key and "openai_api_key" not in result and defaults.openai_api_key:
        result["openai_api_key"] = defaults.openai_api_key

    if not include_api_key:
        result.pop("openai_api_key", None)

    return result
