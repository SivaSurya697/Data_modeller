"""Helper utilities for computing and merging source profiling metadata."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import fmean
from typing import Any, Iterable


def _serialise_value(value: Any) -> Any:
    """Return a JSON serialisable representation of ``value``."""

    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _coerce_numeric(value: Any) -> float | None:
    """Attempt to coerce values to ``float`` for numeric statistics."""

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _now() -> datetime:
    """Return the current time in UTC."""

    return datetime.now(timezone.utc)


def summarise_preview(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate statistics for the supplied preview rows."""

    samples = list(rows)
    column_values: dict[str, list[Any]] = defaultdict(list)
    for row in samples:
        for key, value in row.items():
            column_values[key].append(value)

    column_profiles: dict[str, dict[str, Any]] = {}
    for column, values in column_values.items():
        stats = _build_column_statistics(values)
        column_profiles[column] = {
            "statistics": stats,
            "sample_values": [_serialise_value(value) for value in values[:5]] or None,
        }

    preview_rows = [
        {key: _serialise_value(value) for key, value in row.items()}
        for row in samples[:5]
    ]

    return {
        "profiled_at": _now().isoformat(),
        "sampled_row_count": len(samples),
        "columns": column_profiles,
        "preview_rows": preview_rows or None,
    }


def merge_statistics(
    existing: dict[str, Any] | None, updates: dict[str, Any]
) -> dict[str, Any]:
    """Deep merge ``updates`` into ``existing`` dictionaries."""

    if not existing:
        return {key: value for key, value in updates.items()}

    merged: dict[str, Any] = {**existing}
    for key, value in updates.items():
        if key == "columns":
            current_columns = merged.get("columns", {})
            merged_columns: dict[str, Any] = {**current_columns}
            for column_name, column_value in value.items():
                existing_column = current_columns.get(column_name)
                if isinstance(existing_column, dict) and isinstance(
                    column_value, dict
                ):
                    merged_columns[column_name] = merge_statistics(
                        existing_column, column_value
                    )
                else:
                    merged_columns[column_name] = column_value
            merged["columns"] = merged_columns
        elif (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
            and key != "preview_rows"
        ):
            merged[key] = merge_statistics(merged.get(key, {}), value)
        else:
            merged[key] = value
    return merged


def _build_column_statistics(values: list[Any]) -> dict[str, Any]:
    """Return descriptive statistics for a list of column values."""

    total = len(values)
    nulls = sum(1 for value in values if value is None)
    non_null = [value for value in values if value is not None]
    distinct = len({repr(value) for value in non_null})

    stats: dict[str, Any] = {
        "total": total,
        "nulls": nulls,
        "distinct": distinct,
    }

    numeric_values = [
        number for item in non_null if (number := _coerce_numeric(item)) is not None
    ]
    if numeric_values:
        stats.update(
            {
                "min": min(numeric_values),
                "max": max(numeric_values),
                "avg": fmean(numeric_values),
            }
        )

    if non_null:
        try:
            stats["mode"] = max(set(non_null), key=non_null.count)
        except TypeError:
            # Non-hashable values cannot be placed in a ``set`` for counting.
            pass

    return stats


__all__ = ["merge_statistics", "summarise_preview"]

