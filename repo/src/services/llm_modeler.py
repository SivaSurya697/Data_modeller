"""Prompt builders for the modelling workflows."""
from __future__ import annotations

from typing import Iterable, Sequence

from src.services.llm_client import chat_complete
from src.services.settings import AppSettings

SYSTEM_PROMPT_DRAFT_FRESH = """You are a senior analytics engineer who designs dimensional data models.\nRespond with a JSON object containing the keys `name`, `summary`, `definition`, and optional `changes`.\n- `name`: canonical model name.\n- `summary`: short plain-language overview.\n- `definition`: markdown with headings for Purpose, Grain, Entities, and Important Notes.\n- `changes`: optional array of brief review bullets.\nDo not include any additional narration or Markdown fences in the output."""

SYSTEM_PROMPT_DRAFT_EXTEND = """You are a senior analytics engineer extending an existing data model draft.\nReturn a JSON object with `summary`, `definition`, and optional `changes`.\nEnsure the refreshed definition keeps prior intent while incorporating all requested updates.\nOnly provide the JSON payload."""

SYSTEM_PROMPT_MAPPING_HINTS = """You are a senior analytics engineer producing mapping hints to connect business concepts to source data.\nOutput a JSON object with a `hints` array. Each hint should be a short sentence explaining how to align the model to the available sources.\nDo not add commentary outside of the JSON response."""


def _format_collection(items: Iterable[str] | None, empty_text: str) -> str:
    values = [item.strip() for item in (items or []) if item and item.strip()]
    if not values:
        return empty_text
    return "\n".join(f"- {value}" for value in values)


def _join_sections(sections: Iterable[tuple[str, str]]) -> str:
    lines: list[str] = []
    for title, body in sections:
        lines.append(title)
        lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


def draft_fresh(
    settings: AppSettings,
    *,
    request: str,
    domain_summary: str,
    prior_snippets: Sequence[str] | None = None,
    source_summaries: Sequence[str] | None = None,
    instructions: str | None = None,
) -> str:
    """Create a brand-new model draft using the structured prompt."""

    sections = [
        ("Assignment:", request.strip()),
        ("Domain Summary:", (domain_summary or "Not provided.").strip()),
        (
            "Source Summaries:",
            _format_collection(source_summaries, "- None provided."),
        ),
        (
            "Prior Model Snippets:",
            _format_collection(prior_snippets, "- None provided."),
        ),
    ]
    if instructions and instructions.strip():
        sections.append(("Additional Guidance:", instructions.strip()))

    user_prompt = _join_sections(sections)
    return chat_complete(
        settings,
        [
            {"role": "system", "content": SYSTEM_PROMPT_DRAFT_FRESH},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )


def draft_extend(
    settings: AppSettings,
    *,
    existing_definition: str,
    extension_brief: str,
    prior_snippets: Sequence[str] | None = None,
    source_summaries: Sequence[str] | None = None,
    instructions: str | None = None,
) -> str:
    """Extend an existing draft using the provided context."""

    sections = [
        ("Extension Brief:", extension_brief.strip()),
        ("Current Definition:", existing_definition.strip()),
        (
            "Reference Snippets:",
            _format_collection(prior_snippets, "- None provided."),
        ),
        (
            "Source Summaries:",
            _format_collection(source_summaries, "- None provided."),
        ),
    ]
    if instructions and instructions.strip():
        sections.append(("Additional Guidance:", instructions.strip()))

    user_prompt = _join_sections(sections)
    return chat_complete(
        settings,
        [
            {"role": "system", "content": SYSTEM_PROMPT_DRAFT_EXTEND},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )


def mapping_hints(
    settings: AppSettings,
    *,
    model_definition: str,
    integration_context: str,
    prior_snippets: Sequence[str] | None = None,
    source_summaries: Sequence[str] | None = None,
    instructions: str | None = None,
) -> str:
    """Generate mapping hints to align the draft with upstream sources."""

    sections = [
        ("Integration Context:", integration_context.strip()),
        ("Model Definition:", model_definition.strip()),
        (
            "Source Summaries:",
            _format_collection(source_summaries, "- None provided."),
        ),
        (
            "Reference Snippets:",
            _format_collection(prior_snippets, "- None provided."),
        ),
    ]
    if instructions and instructions.strip():
        sections.append(("Additional Guidance:", instructions.strip()))

    user_prompt = _join_sections(sections)
    return chat_complete(
        settings,
        [
            {"role": "system", "content": SYSTEM_PROMPT_MAPPING_HINTS},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )


__all__ = ["draft_fresh", "draft_extend", "mapping_hints"]
