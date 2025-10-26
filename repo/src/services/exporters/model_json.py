"""Utilities for exporting model JSON artifacts."""

from __future__ import annotations

import json
from pathlib import Path


def emit_model(model_json_str: str, out_path: str) -> None:
    """Validate and write a model JSON string to ``out_path``.

    The ``model_json_str`` must be valid JSON. The JSON is pretty-printed with an
    indentation of two spaces and written using UTF-8 encoding. The destination
    directory is created automatically if it does not already exist.

    Args:
        model_json_str: Raw JSON string representation of the model.
        out_path: Destination file path for the JSON artifact.

    Raises:
        ValueError: If ``model_json_str`` does not contain valid JSON.
    """

    try:
        parsed_json = json.loads(model_json_str)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError("Invalid model JSON") from exc

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(parsed_json, indent=2, ensure_ascii=False)
    output_path.write_text(f"{json_text}\n", encoding="utf-8")


def bump_version_str(curr: str | None) -> str:
    """Return the next semantic minor version string.

    If ``curr`` is in the format ``"<major>.<minor>"`` both parts will be parsed
    as integers and the minor component is incremented. When ``curr`` is ``None``
    or not in a valid ``major.minor`` format the version resets to ``"1.0"``.

    Args:
        curr: The current version string.

    Returns:
        The bumped version string.
    """

    if not curr:
        return "1.0"

    parts = curr.split(".")
    if len(parts) != 2:
        return "1.0"

    major_part, minor_part = parts
    if not (major_part.isdigit() and minor_part.isdigit()):
        return "1.0"

    major = int(major_part)
    minor = int(minor_part)
    return f"{major}.{minor + 1}"


__all__ = ["emit_model", "bump_version_str"]

