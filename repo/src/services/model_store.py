"""Helpers for locating published model artifacts on disk."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def parse_version(version_text: str) -> tuple[int, int]:
    """Return a comparable tuple for semantic-like version strings.

    Parameters
    ----------
    version_text:
        String containing the version suffix extracted from an artifact name.

    Notes
    -----
    Only ``major.minor`` forms are considered valid.  Any parsing error
    results in ``(0, 0)`` which naturally sorts before legitimate versions.
    """

    parts = version_text.split(".")
    if len(parts) != 2:
        return (0, 0)
    try:
        major = int(parts[0])
        minor = int(parts[1])
    except ValueError:
        return (0, 0)
    return (major, minor)


def _candidate_paths(artifacts_dir: Path, domain: str) -> Iterable[Path]:
    pattern = f"model_{domain}_*.json"
    return artifacts_dir.glob(pattern)


def latest_model_path(artifacts_dir: str, domain: str) -> str | None:
    """Return the newest published model artifact for ``domain``.

    The helper scans ``artifacts_dir`` for files following the naming
    convention ``model_<domain>_<version>.json`` and returns the path with the
    highest version number.  ``None`` is returned when no matching files exist.
    """

    base_path = Path(artifacts_dir)
    if not base_path.exists() or not base_path.is_dir():
        return None

    prefix = f"model_{domain}_"
    candidates: list[tuple[tuple[int, int], Path]] = []
    for path in _candidate_paths(base_path, domain):
        version_part = path.stem[len(prefix) :]
        version = parse_version(version_part)
        if version <= (0, 0):
            continue
        candidates.append((version, path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return str(candidates[-1][1])


def load_latest_model_json(artifacts_dir: str, domain: str) -> str | None:
    """Return the serialized JSON for the latest model if available."""

    path = latest_model_path(artifacts_dir, domain)
    if path is None:
        return None
    file_path = Path(path)
    try:
        return file_path.read_text(encoding="utf-8")
    except OSError:
        return None


__all__ = ["latest_model_path", "load_latest_model_json", "parse_version"]

