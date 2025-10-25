"""Utility functions for proposing attribute-to-column mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from rapidfuzz import fuzz


_SEMANTIC_HINTS: dict[str, tuple[str, ...]] = {
    "id": ("id", "identifier", "key"),
    "dob": ("dob", "birth", "birthdate", "birth_date", "date_of_birth"),
    "gender": ("gender", "sex"),
    "npi": ("npi",),
    "icd": ("icd",),
    "cpt": ("cpt",),
    "ndc": ("ndc",),
}

_CANONICAL_DTYPES: dict[str, set[str]] = {
    "string": {
        "string",
        "varchar",
        "char",
        "text",
        "nvarchar",
        "character varying",
    },
    "int": {"int", "integer", "bigint", "smallint", "number"},
    "decimal": {"decimal", "numeric", "float", "double", "real"},
    "date": {"date", "datetime", "timestamp", "timestamptz"},
}

_WEAK_COMPAT: set[frozenset[str]] = {
    frozenset({"string", "decimal"}),
    frozenset({"string", "int"}),
    frozenset({"decimal", "int"}),
}


def _normalise_dtype(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def name_similarity(a: str, b: str) -> float:
    """Return a normalised similarity score between two attribute names."""

    if not a or not b:
        return 0.0
    return fuzz.token_sort_ratio(a, b) / 100.0


def dtype_compat_score(attr_dtype: str | None, col_dtype: str | None) -> float:
    """Return a compatibility score for attribute and column data types."""

    attr_norm = _normalise_dtype(attr_dtype)
    col_norm = _normalise_dtype(col_dtype)
    if not attr_norm or not col_norm:
        return 0.0

    attr_key = next(
        (canonical for canonical, aliases in _CANONICAL_DTYPES.items() if attr_norm in aliases),
        attr_norm,
    )
    col_key = next(
        (canonical for canonical, aliases in _CANONICAL_DTYPES.items() if col_norm in aliases),
        col_norm,
    )

    if attr_key == col_key:
        return 1.0

    if frozenset({attr_key, col_key}) in _WEAK_COMPAT:
        return 0.25

    return 0.0


def semantic_hint_score(semantic_type: str | None, column_name: str) -> float:
    """Return a score reflecting semantic keyword alignment."""

    if not semantic_type or not column_name:
        return 0.0

    semantic = semantic_type.lower()
    col = column_name.lower()
    score = 0.0

    for key, aliases in _SEMANTIC_HINTS.items():
        if any(alias in semantic for alias in aliases):
            if key in col or any(alias in col for alias in aliases):
                score = max(score, 1.0)
            elif col.startswith(key):
                score = max(score, 0.75)
            else:
                score = max(score, 0.5)

    return score


def column_evidence_score(col_name: str, stats: dict[str, Any] | None) -> float:
    """Return an evidence score based on profiling statistics."""

    if not stats:
        return 0.0

    col_lower = col_name.lower()
    score = 0.0

    null_pct = stats.get("null_pct")
    if null_pct is None:
        null_pct = stats.get("null_ratio")
    if null_pct is None:
        null_pct = stats.get("pct_null")
    if null_pct is None and stats.get("total"):
        total = stats.get("total")
        nulls = stats.get("nulls") or stats.get("null_count")
        if nulls is not None and total:
            try:
                null_pct = float(nulls) / float(total)
            except ZeroDivisionError:
                null_pct = None

    if isinstance(null_pct, (int, float)):
        if null_pct <= 0.05:
            score += 0.6
        elif null_pct <= 0.2:
            score += 0.4
        elif null_pct <= 0.35:
            score += 0.2

    distinct = stats.get("distinct_count") or stats.get("distinct") or stats.get("approx_distinct")
    total = stats.get("total") or stats.get("count") or stats.get("row_count")

    if isinstance(distinct, (int, float)) and isinstance(total, (int, float)) and total:
        try:
            uniqueness = float(distinct) / float(total)
        except ZeroDivisionError:  # pragma: no cover - defensive guard
            uniqueness = 0.0
        if "id" in col_lower:
            if uniqueness >= 0.9:
                score += 0.4
            elif uniqueness >= 0.5:
                score += 0.2
        else:
            if uniqueness <= 0.1:
                score += 0.2
            elif uniqueness <= 0.5:
                score += 0.1

    return min(score, 1.0)


def candidate_confidence(
    attr: dict[str, Any],
    column_name: str,
    col_dtype: str | None,
    stats: dict[str, Any] | None,
) -> float:
    """Return the combined confidence score for a mapping candidate."""

    name_score = name_similarity(attr.get("name", ""), column_name)
    dtype_score = dtype_compat_score(attr.get("datatype") or attr.get("data_type"), col_dtype)
    semantic_source = attr.get("semantic_type") or attr.get("name", "")
    semantic_score = semantic_hint_score(semantic_source, column_name)
    evidence_score = column_evidence_score(column_name, stats)

    combined = (
        0.5 * name_score
        + 0.2 * dtype_score
        + 0.2 * semantic_score
        + 0.1 * evidence_score
    )
    return min(combined, 1.0)


@dataclass(frozen=True)
class _CandidateScore:
    name: float
    dtype: float
    semantic: float
    evidence: float


def _build_rationale(col_name: str, scores: _CandidateScore, stats: dict[str, Any] | None) -> str:
    reasons: list[str] = []

    if scores.name >= 0.85:
        reasons.append("strong name match")
    elif scores.name >= 0.6:
        reasons.append("partial name similarity")

    if scores.dtype >= 0.85:
        reasons.append("compatible data type")
    elif scores.dtype >= 0.25:
        reasons.append("loosely compatible type")

    if scores.semantic >= 0.75:
        reasons.append("semantic keyword alignment")
    elif scores.semantic >= 0.5:
        reasons.append("possible semantic hint")

    if scores.evidence >= 0.5:
        reasons.append("good profiling coverage")
    elif scores.evidence >= 0.25:
        reasons.append("some statistical support")

    if not reasons:
        reasons.append(f"column {col_name} has limited supporting evidence")

    return ", ".join(reasons)


def autoplan(
    entity: dict[str, Any],
    attributes: Iterable[dict[str, Any]],
    sources: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return mapping candidates for each attribute across the supplied sources."""

    results: list[dict[str, Any]] = []
    source_list = list(sources)

    for attribute in attributes:
        attr_name = attribute.get("name") or ""
        attr_id = attribute.get("id")
        attr_semantic = attribute.get("semantic_type") or attr_name
        attr_dtype = attribute.get("datatype") or attribute.get("data_type")

        candidates: list[dict[str, Any]] = []
        for source in source_list:
            schema = source.get("schema_json") or {}
            stats_json = source.get("stats_json") or {}
            source_name = source.get("name") or ""
            source_id = source.get("id")

            for column_name, column_dtype in schema.items():
                column_stats = stats_json.get(column_name)
                name_score = name_similarity(attr_name, column_name)
                dtype_score = dtype_compat_score(attr_dtype, column_dtype)
                semantic_score = semantic_hint_score(attr_semantic, column_name)
                evidence_score = column_evidence_score(column_name, column_stats)
                scores = _CandidateScore(
                    name=name_score,
                    dtype=dtype_score,
                    semantic=semantic_score,
                    evidence=evidence_score,
                )

                combined = candidate_confidence(attribute, column_name, column_dtype, column_stats)
                if combined <= 0.0:
                    continue

                rationale = _build_rationale(column_name, scores, column_stats)
                column_path = f"{source_name}.{column_name}" if source_name else column_name

                candidates.append(
                    {
                        "source_table_id": source_id,
                        "source": column_path,
                        "column_name": column_name,
                        "column_path": column_path,
                        "confidence": combined,
                        "rationale": rationale,
                        "transforms": None,
                        "join_recipe": None,
                        "scores": {
                            "name": scores.name,
                            "dtype": scores.dtype,
                            "semantic": scores.semantic,
                            "evidence": scores.evidence,
                        },
                    }
                )

        candidates.sort(key=lambda candidate: candidate["confidence"], reverse=True)
        trimmed_candidates = candidates[:3]

        results.append(
            {
                "attribute": attr_name,
                "attribute_id": attr_id,
                "candidates": trimmed_candidates,
            }
        )

    return results


__all__ = [
    "autoplan",
    "candidate_confidence",
    "column_evidence_score",
    "dtype_compat_score",
    "name_similarity",
    "semantic_hint_score",
]

