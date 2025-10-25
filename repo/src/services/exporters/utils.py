"""Utility helpers for exporter modules."""
from __future__ import annotations

from pathlib import Path


def prepare_artifact_path(base_dir: Path, filename: str) -> Path:
    """Return a safe path for an artifact inside ``base_dir``.

    Ensures the directory exists and guards against path traversal by verifying
    that the final resolved path resides within the provided base directory.
    """

    base_resolved = base_dir.resolve()
    base_resolved.mkdir(parents=True, exist_ok=True)

    candidate = (base_resolved / filename).resolve()
    if candidate == base_resolved or not candidate.is_relative_to(base_resolved):
        raise ValueError("Resolved artifact path must reside within the artifacts directory")
    return candidate
