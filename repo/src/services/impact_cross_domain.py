"""Cross-domain impact analysis helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from src.models.tables import Domain


_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenise(text: str | None) -> set[str]:
    """Return a set of normalised tokens extracted from ``text``."""

    if not text:
        return set()

    tokens: set[str] = set()
    for raw in _WORD_RE.findall(text.lower()):
        if len(raw) < 4:
            continue
        tokens.add(raw)
        if raw.endswith("s") and len(raw) > 4:
            tokens.add(raw[:-1])
    return tokens


def _collect_domain_tokens(domain: Domain) -> set[str]:
    tokens = _tokenise(domain.name)
    tokens.update(_tokenise(domain.description))
    for entity in domain.entities:
        tokens.update(_tokenise(entity.name))
        tokens.update(_tokenise(entity.description))
    return tokens


@dataclass(slots=True)
class ImpactFinding:
    """Description of a suggested cross-domain review task."""

    target_domain: Domain
    title: str
    details: str


def identify_impacted_domains(
    new_domain: Domain, existing_domains: Sequence[Domain]
) -> list[ImpactFinding]:
    """Return review findings for domains that share concepts with ``new_domain``."""

    if not existing_domains:
        return []

    new_tokens = _collect_domain_tokens(new_domain)
    findings: list[ImpactFinding] = []

    if not new_tokens:
        return findings

    for domain in existing_domains:
        shared_tokens = sorted(_collect_domain_tokens(domain) & new_tokens)
        if not shared_tokens:
            continue

        headline_terms = ", ".join(shared_tokens[:5])
        details = (
            "Shared terminology detected with "
            f"domain '{domain.name}': {headline_terms}."
        )
        findings.append(
            ImpactFinding(
                target_domain=domain,
                title=f"Review overlap with {domain.name}",
                details=details,
            )
        )

    findings.sort(key=lambda finding: finding.target_domain.name.lower())
    return findings


__all__ = ["ImpactFinding", "identify_impacted_domains"]

