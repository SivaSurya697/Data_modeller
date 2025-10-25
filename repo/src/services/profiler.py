"""Pure helper utilities for building lightweight data profiles."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict


class ColumnProfile(TypedDict):
    """Statistics derived from a sampled column."""

    null_count: int
    null_pct: float
    distinct_count: int


class ProfileResult(TypedDict):
    """Output structure describing a sampled preview."""

    rows: list[dict[str, Any]]
    columns: dict[str, ColumnProfile]
    sampled: int


class ColumnSummary(TypedDict):
    """Uniform representation of a schema column."""

    name: str
    type: str | None
    nullable: bool
    description: str | None


class SchemaSummary(TypedDict):
    """Structured summary of schema metadata."""

    columns: list[ColumnSummary]
    counts: dict[str, Any]


def summarize_schema(
    schema: Sequence[Mapping[str, Any]]
    | Mapping[str, Mapping[str, Any]]
    | None,
) -> SchemaSummary:
    """Return a deterministic summary for a collection of schema fields.

    Parameters
    ----------
    schema:
        An iterable of column descriptors or a mapping keyed by column name.
        Each element is expected to provide ``name``, ``type``, ``nullable`` and
        optionally ``description`` attributes, but the helper tolerates missing
        fields and coerces them into sensible defaults.

    Returns
    -------
    SchemaSummary
        A normalised representation containing ordered column metadata and
        aggregate counts (total, nullable, required and by type).
    """

    columns: list[ColumnSummary] = []

    if not schema:
        return {
            "columns": columns,
            "counts": {
                "total": 0,
                "nullable": 0,
                "required": 0,
                "by_type": {},
            },
        }

    if isinstance(schema, Mapping):
        items = [
            _coerce_column_summary(index, key, value)
            for index, (key, value) in enumerate(schema.items())
        ]
    else:
        items = [
            _coerce_column_summary(index, None, value)
            for index, value in enumerate(schema)
        ]

    columns.extend(sorted(items, key=lambda column: column["name"].lower()))

    nullable_count = sum(1 for column in columns if column["nullable"])
    type_counts: dict[str, int] = {}
    for column in columns:
        type_name = column["type"] or "unknown"
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

    return {
        "columns": columns,
        "counts": {
            "total": len(columns),
            "nullable": nullable_count,
            "required": len(columns) - nullable_count,
            "by_type": dict(sorted(type_counts.items())),
        },
    }


def profile_preview_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    max_rows: int = 50,
) -> ProfileResult:
    """Generate a deterministic profile for a collection of preview rows.

    The function inspects the first ``max_rows`` rows, computes per-column
    statistics (null count, null percentage and distinct count) and returns the
    sampled rows themselves for downstream preview purposes.

    Parameters
    ----------
    rows:
        Iterable of mapping-like objects representing preview rows.
    max_rows:
        Upper bound on the number of rows to profile and return. Negative values
        are treated as zero.

    Returns
    -------
    ProfileResult
        A dictionary containing the sampled rows, column level statistics and
        the number of rows included in the calculation.
    """

    if max_rows < 0:
        max_rows = 0

    materialised_rows = [_coerce_row(row) for row in rows]
    limited_rows = materialised_rows[:max_rows]
    sample_count = len(limited_rows)

    if sample_count == 0:
        return {"rows": [], "columns": {}, "sampled": 0}

    column_names = sorted({key for row in limited_rows for key in row})
    column_profiles: dict[str, ColumnProfile] = {}

    for column_name in column_names:
        values = [row.get(column_name) for row in limited_rows]
        null_count = sum(value is None for value in values)
        non_null_values = [value for value in values if value is not None]
        distinct_count = len({_normalise_distinct(value) for value in non_null_values})
        null_pct = (null_count / sample_count * 100.0) if sample_count else 0.0
        column_profiles[column_name] = {
            "null_count": null_count,
            "null_pct": null_pct,
            "distinct_count": distinct_count,
        }

    return {
        "rows": limited_rows,
        "columns": column_profiles,
        "sampled": sample_count,
    }


def merge_stats(
    profiles: Iterable[ProfileResult],
    *,
    max_rows: int | None = None,
) -> ProfileResult:
    """Combine multiple profile samples into a single aggregated profile.

    Parameters
    ----------
    profiles:
        Iterable of previously generated :func:`profile_preview_rows` results.
    max_rows:
        Optional cap for the number of rows to keep in the merged preview. If
        omitted, all available rows are considered.

    Returns
    -------
    ProfileResult
        A profile matching the structure of :func:`profile_preview_rows` with
        aggregated column statistics and the combined sampled row total.
    """

    profile_list = [profile for profile in profiles if profile]
    if not profile_list:
        return {"rows": [], "columns": {}, "sampled": 0}

    aggregated_rows: list[dict[str, Any]] = []
    sampled_total = 0
    for profile in profile_list:
        aggregated_rows.extend(profile.get("rows", []))
        sampled_total += int(profile.get("sampled", len(profile.get("rows", []))))

    merged = profile_preview_rows(aggregated_rows, max_rows=len(aggregated_rows))
    if max_rows is not None:
        max_rows = max(0, max_rows)
        merged["rows"] = merged["rows"][:max_rows]
    merged["sampled"] = sampled_total
    return merged


def _coerce_column_summary(
    index: int,
    explicit_name: str | None,
    raw: Mapping[str, Any] | Any,
) -> ColumnSummary:
    """Normalise a raw column definition into a :class:`ColumnSummary`."""

    if isinstance(raw, Mapping):
        name = str(raw.get("name", explicit_name or f"column_{index}"))
        type_value = raw.get("type") or raw.get("data_type") or raw.get("python_type")
        description = raw.get("description")
        nullable_source = (
            raw.get("nullable")
            if "nullable" in raw
            else raw.get("is_nullable")
        )
    else:
        name = str(explicit_name or f"column_{index}")
        type_value = raw
        description = None
        nullable_source = None

    return {
        "name": name,
        "type": _coerce_type(type_value),
        "nullable": _coerce_bool(nullable_source, default=True),
        "description": str(description) if description is not None else None,
    }


def _coerce_type(value: Any) -> str | None:
    """Represent a raw type descriptor as a deterministic string."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(sorted(str(item) for item in value)) or None
    if isinstance(value, Mapping):
        items = ", ".join(
            f"{key}={_coerce_type(sub_value) or 'None'}"
            for key, sub_value in sorted(value.items(), key=lambda item: str(item[0]))
        )
        return items or None
    return str(value)


def _coerce_bool(value: Any, *, default: bool) -> bool:
    """Coerce a potentially ambiguous truthy value to ``bool``."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"true", "1", "yes", "y", "t"}:
            return True
        if normalised in {"false", "0", "no", "n", "f"}:
            return False
        return bool(normalised)
    return bool(value)


def _coerce_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-serialisable representation of a raw row mapping."""

    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}

    try:
        derived = dict(row)
    except Exception as exc:  # pragma: no cover - defensive branch
        raise TypeError("Preview rows must be mapping compatible") from exc
    return {str(key): value for key, value in derived.items()}


def _normalise_distinct(value: Any) -> tuple[str, Any]:
    """Return a hashable token describing ``value`` for distinct calculations."""

    if isinstance(value, (str, int, float, bool, type(None))):
        return (type(value).__name__, value)
    if isinstance(value, bytes):
        return ("bytes", value)
    if isinstance(value, Mapping):
        return (
            "dict",
            tuple(
                (str(key), _normalise_distinct(sub_value))
                for key, sub_value in sorted(value.items(), key=lambda item: str(item[0]))
            ),
        )
    if isinstance(value, (list, tuple)):
        return (
            type(value).__name__,
            tuple(_normalise_distinct(item) for item in value),
        )
    if isinstance(value, (set, frozenset)):
        return (
            type(value).__name__,
            tuple(sorted(_normalise_distinct(item) for item in value)),
        )
    return (type(value).__name__, repr(value))


__all__ = [
    "ColumnProfile",
    "ProfileResult",
    "ColumnSummary",
    "SchemaSummary",
    "summarize_schema",
    "profile_preview_rows",
    "merge_stats",
]
