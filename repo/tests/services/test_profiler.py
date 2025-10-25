"""Tests for the profiling helper utilities."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.profiler import (  # noqa: E402  # pylint: disable=wrong-import-position
    merge_stats,
    profile_preview_rows,
    summarize_schema,
)


def test_summarize_schema_with_empty_input() -> None:
    """Empty schema inputs should yield zero counts."""

    summary = summarize_schema(None)

    assert summary["columns"] == []
    assert summary["counts"] == {
        "total": 0,
        "nullable": 0,
        "required": 0,
        "by_type": {},
    }


def test_summarize_schema_handles_mixed_descriptors() -> None:
    """Schema summarisation copes with mappings and lists containing metadata."""

    schema: dict[str, dict[str, Any]] = {
        "id": {"type": "integer", "nullable": False},
        "name": {"data_type": "text", "description": "Label"},
    }
    summary = summarize_schema(schema)

    assert {column["name"] for column in summary["columns"]} == {"id", "name"}
    id_column = next(column for column in summary["columns"] if column["name"] == "id")
    assert id_column == {
        "name": "id",
        "type": "integer",
        "nullable": False,
        "description": None,
    }
    name_column = next(
        column for column in summary["columns"] if column["name"] == "name"
    )
    assert name_column == {
        "name": "name",
        "type": "text",
        "nullable": True,
        "description": "Label",
    }
    assert summary["counts"]["total"] == 2
    assert summary["counts"]["nullable"] == 1
    assert summary["counts"]["required"] == 1
    assert summary["counts"]["by_type"] == {"integer": 1, "text": 1}


def test_profile_preview_rows_handles_empty_samples() -> None:
    """Profiling with no rows should return an empty result structure."""

    result = profile_preview_rows([], max_rows=5)

    assert result == {"rows": [], "columns": {}, "sampled": 0}


def test_profile_preview_rows_mixed_datatypes() -> None:
    """Distinct calculations account for differing Python types."""

    rows = [
        {"col": 1, "other": None},
        {"col": "1"},
        {"col": 1.0, "other": {"nested": 1}},
        {"col": None, "other": {"nested": 1}},
    ]
    result = profile_preview_rows(rows, max_rows=3)

    assert result["sampled"] == 3
    assert len(result["rows"]) == 3
    assert set(result["columns"].keys()) == {"col", "other"}
    col_stats = result["columns"]["col"]
    assert col_stats["null_count"] == 0
    # Distinct count should treat int, string and float as separate values
    assert col_stats["distinct_count"] == 3
    other_stats = result["columns"]["other"]
    assert other_stats["null_count"] == 2
    assert pytest.approx(other_stats["null_pct"]) == 200.0 / 3


def test_merge_stats_combines_profiles() -> None:
    """Merged statistics retain combined counts and respect row limits."""

    left = profile_preview_rows(
        [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": None},
        ],
        max_rows=5,
    )
    right = profile_preview_rows(
        [
            {"id": 3, "name": "Bob"},
            {"id": None, "name": "Carol"},
        ],
        max_rows=5,
    )

    merged = merge_stats([left, right], max_rows=3)

    assert merged["sampled"] == 4
    assert len(merged["rows"]) == 3
    assert merged["columns"]["id"]["null_count"] == 1
    assert merged["columns"]["id"]["distinct_count"] == 3
    assert merged["columns"]["name"]["null_count"] == 1
    assert merged["columns"]["name"]["distinct_count"] == 3
