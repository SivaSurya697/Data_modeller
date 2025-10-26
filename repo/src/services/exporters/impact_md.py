"""Utilities for generating impact report markdown artifacts."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


def summarize_impact(impact_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise impact items by level.

    Args:
        impact_items: A collection of impact dictionaries containing an
            ``impact_level`` key.

    Returns:
        A summary dictionary with the total count and counts for ``high``,
        ``medium``, and ``low`` impact levels.
    """

    level_counter: Counter[str] = Counter()
    for item in impact_items:
        level = str(item.get("impact_level", "")).lower()
        if level not in {"high", "medium", "low"}:
            continue
        level_counter[level] += 1

    return {
        "total": len(impact_items),
        "by_level": {
            "high": level_counter.get("high", 0),
            "medium": level_counter.get("medium", 0),
            "low": level_counter.get("low", 0),
        },
    }


def emit_impact_md(impact_items: list[dict[str, Any]], out_path: str) -> None:
    """Write a markdown report describing ``impact_items`` to ``out_path``."""

    summary = summarize_impact(impact_items)
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = ["# Impact Report\n\n"]
    lines.append(f"- Total items: {summary['total']}\n")
    lines.append("- Breakdown by level (high/medium/low)\n")
    lines.append(f"  - High: {summary['by_level']['high']}\n")
    lines.append(f"  - Medium: {summary['by_level']['medium']}\n")
    lines.append(f"  - Low: {summary['by_level']['low']}\n\n")

    lines.append("| dimension | consumer | impact_level | explanation |\n")
    lines.append("| --- | --- | --- | --- |\n")

    if impact_items:
        for item in impact_items:
            dimension = item.get("dimension", "")
            consumer = item.get("consumer", "")
            impact_level = item.get("impact_level", "")
            explanation = item.get("explanation", "")
            lines.append(
                f"| {dimension} | {consumer} | {impact_level} | {explanation} |\n"
            )
    else:
        lines.append("| _None_ | _None_ | _None_ | _No impact recorded_ |\n")

    output_path.write_text("".join(lines), encoding="utf-8")


__all__ = ["emit_impact_md", "summarize_impact"]

