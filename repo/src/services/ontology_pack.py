"""Lightweight healthcare payor ontology used for MECE coverage analysis."""

from __future__ import annotations

from typing import Optional

ONTOLOGY = {
    "entities": {
        "beneficiary": {
            "synonyms": ["member", "insured", "subscriber", "patient"],
            "preferred_attributes": {
                "beneficiary_id": [
                    "member_id",
                    "subscriber_id",
                    "patient_id",
                    "person_id",
                ],
                "date_of_birth": ["dob"],
                "gender": ["sex"],
                "national_id": ["nid", "ssn"],
                "effective_date": ["elig_start", "start_date"],
                "termination_date": ["elig_end", "end_date"],
            },
        },
        "provider": {
            "synonyms": [
                "rendering_provider",
                "servicing_provider",
                "physician",
                "hcp",
            ],
            "preferred_attributes": {
                "provider_id": ["npi", "physician_id"],
                "provider_name": ["name"],
                "specialty": [],
                "facility_id": ["location_id", "site_id"],
            },
        },
        "scheme": {
            "synonyms": ["plan", "product", "policy"],
            "preferred_attributes": {
                "scheme_id": ["plan_id", "policy_id", "product_id"],
                "scheme_name": ["plan_name", "product_name"],
            },
        },
        "claim": {
            "synonyms": ["medical_claim", "encounter", "invoice"],
            "preferred_attributes": {
                "claim_id": [],
                "claim_date": ["service_date", "dos"],
                "total_amount": ["billed_amount", "charged_amount", "payable_amount"],
            },
        },
        "claim_line": {
            "synonyms": ["line_item", "service_line"],
            "preferred_attributes": {
                "claim_line_id": ["line_id"],
                "diagnosis_code": ["icd", "icd10"],
                "procedure_code": ["cpt", "hcpcs"],
                "quantity": [],
                "line_amount": ["allowed_amount", "paid_amount"],
            },
        },
        "authorization": {
            "synonyms": ["preauth", "prior_auth", "referral"],
            "preferred_attributes": {
                "authorization_id": ["auth_id"],
                "request_date": [],
                "decision": ["status"],
            },
        },
        "remittance": {
            "synonyms": ["era", "eob", "payment_advice"],
            "preferred_attributes": {
                "remittance_id": [],
                "payment_date": [],
                "payment_amount": [],
            },
        },
    },
    "semantic_aliases": {
        "id": ["id", "*_id", "*_key", "code", "npi", "mrn", "nid", "ssn"],
        "date": ["date", "_dt", "_at", "from", "to", "effective", "termination"],
        "money": ["amount", "charge", "billed", "allowed", "paid", "payable"],
        "diagnosis": ["icd", "icd10", "icd9"],
        "procedure": ["cpt", "hcpcs", "icd_proc"],
        "drug": ["ndc"],
    },
}


def _normalise(value: str) -> str:
    return value.strip().lower()


def canonical_entity_name(name: str) -> str:
    """Map a name or synonym to a canonical ontology key when possible."""

    candidate = _normalise(name)
    for canonical, data in ONTOLOGY["entities"].items():
        if candidate == canonical:
            return canonical
        if candidate in map(_normalise, data.get("synonyms", [])):
            return canonical
    return candidate


def suggest_preferred_attr(entity_canon: str, attr_name: str) -> Optional[str]:
    """Return the canonical attribute if ``attr_name`` matches a known synonym."""

    if not attr_name:
        return None

    canonical_entity = ONTOLOGY["entities"].get(entity_canon)
    if not canonical_entity:
        return None

    candidate = _normalise(attr_name)
    for preferred, synonyms in canonical_entity.get("preferred_attributes", {}).items():
        if candidate == _normalise(preferred):
            return preferred
        if any(candidate == _normalise(alias) for alias in synonyms):
            return preferred
    return None


__all__ = ["ONTOLOGY", "canonical_entity_name", "suggest_preferred_attr"]
