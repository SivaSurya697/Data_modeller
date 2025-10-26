from __future__ import annotations

import json
from copy import deepcopy
from typing import Dict, List, Optional, Tuple


# -------- Core helpers --------
def parse_model_json(model_json_str: str) -> Dict:
    """Parse and normalise a model JSON string.

    The helper ensures the returned dictionary exposes the keys used by the
    modeller even when the baseline JSON omits them.  Missing collections are
    initialised to empty lists to simplify downstream processing.
    """

    model = json.loads(model_json_str)
    model.setdefault("entities", [])
    model.setdefault("relationships", [])
    model.setdefault("dictionary", [])
    model.setdefault("shared_dim_refs", [])
    return model


def index_entities(model: Dict) -> Dict[str, Dict]:
    """Return a dictionary keyed by entity name."""

    return {entity.get("name"): entity for entity in model.get("entities", []) if entity.get("name")}


def index_relationships(model: Dict) -> Dict[Tuple[str, str], Dict]:
    """Return a dictionary keyed by the (from, to) tuple of each relationship."""

    index: Dict[Tuple[str, str], Dict] = {}
    for rel in model.get("relationships", []):
        from_name = rel.get("from")
        to_name = rel.get("to")
        if from_name and to_name:
            index[(from_name, to_name)] = rel
    return index


# -------- Apply single change --------
def apply_change(model: Dict, change: Dict, baseline_idx: Dict) -> Tuple[bool, str]:
    """Apply a single change dictionary to ``model``.

    Parameters
    ----------
    model:
        Mutable model dictionary that will be updated in place.
    change:
        Dictionary describing the change to apply.  Supported actions include
        ``add_*``, ``update_*`` and ``delete_*`` for entities and relationships.
    baseline_idx:
        Snapshot of indices for the model prior to processing the batch.  The
        value is recomputed by :func:`apply_changes` after each mutation; it is
        included here for API compatibility and future diagnostics.

    Returns
    -------
    tuple[bool, str]
        ``True`` when the change applied successfully along with a human
        readable message.  ``False`` indicates the change failed and includes a
        descriptive error message.
    """

    action = str(change.get("action") or "").strip()
    target = str(change.get("target") or "").strip()
    after_payload = change.get("after") or {}

    entities = model.get("entities", [])
    relationships = model.get("relationships", [])

    if action in {"add_entity", "update_entity", "delete_entity"}:
        entities_by_name = index_entities(model)
        target_name = target or str(after_payload.get("name") or "").strip()

        if action == "add_entity":
            if not target_name:
                return False, "Entity name is required for add_entity"
            if target_name in entities_by_name:
                return False, f"Entity '{target_name}' already exists"
            new_entity = deepcopy(after_payload)
            new_entity.setdefault("name", target_name)
            entities.append(new_entity)
            return True, f"Added entity {target_name}"

        if action == "update_entity":
            if not target_name:
                target_name = target
            if target_name not in entities_by_name:
                return False, f"Entity '{target_name}' not found"
            entity = entities_by_name[target_name]
            entity.update(after_payload)
            if target_name:
                entity.setdefault("name", target_name)
            return True, f"Updated entity {target_name or entity.get('name')}"

        if action == "delete_entity":
            if not target_name:
                return False, "Entity name is required for delete_entity"
            if target_name not in entities_by_name:
                return False, f"Entity '{target_name}' not found"
            model["entities"] = [
                entity for entity in entities if entity.get("name") != target_name
            ]
            model["relationships"] = [
                rel
                for rel in relationships
                if rel.get("from") != target_name and rel.get("to") != target_name
            ]
            return True, f"Deleted entity {target_name}"

    if action in {"add_relationship", "update_relationship", "delete_relationship"}:
        target_text = target
        from_name = str(after_payload.get("from") or "").strip()
        to_name = str(after_payload.get("to") or "").strip()
        if (not from_name or not to_name) and "->" in target_text:
            left, right = (part.strip() for part in target_text.split("->", 1))
            from_name = from_name or left
            to_name = to_name or right
        if not from_name or not to_name:
            return False, f"Invalid relationship target '{target_text}', expected 'From->To'"

        relationships_by_pair = index_relationships(model)
        key = (from_name, to_name)

        if action == "add_relationship":
            if key in relationships_by_pair:
                return False, f"Relationship {from_name}->{to_name} already exists"
            new_relationship = deepcopy(after_payload)
            new_relationship.setdefault("from", from_name)
            new_relationship.setdefault("to", to_name)
            relationships.append(new_relationship)
            return True, f"Added relationship {from_name}->{to_name}"

        if action == "update_relationship":
            if key not in relationships_by_pair:
                return False, f"Relationship {from_name}->{to_name} not found"
            relationship = relationships_by_pair[key]
            relationship.update(after_payload)
            relationship.setdefault("from", from_name)
            relationship.setdefault("to", to_name)
            return True, f"Updated relationship {from_name}->{to_name}"

        if action == "delete_relationship":
            if key not in relationships_by_pair:
                return False, f"Relationship {from_name}->{to_name} not found"
            model["relationships"] = [
                rel
                for rel in relationships
                if not (rel.get("from") == from_name and rel.get("to") == to_name)
            ]
            return True, f"Deleted relationship {from_name}->{to_name}"

    return False, f"Unsupported action '{action}'"


# -------- Dictionary updates --------
def apply_dictionary_updates(model: Dict, dict_updates: List[Dict]) -> None:
    """Upsert dictionary terms from ``dict_updates`` into ``model``."""

    dictionary = model.setdefault("dictionary", [])
    by_term = {entry.get("term"): entry for entry in dictionary if entry.get("term")}
    for update in dict_updates or []:
        if not isinstance(update, dict):
            continue
        term = str(update.get("term") or "").strip()
        if not term:
            continue
        if term in by_term:
            by_term[term].update(update)
        else:
            new_entry = deepcopy(update)
            new_entry["term"] = term
            dictionary.append(new_entry)
            by_term[term] = new_entry


# -------- Batch apply --------
def apply_changes(
    model_json_str: str,
    proposed_changes: List[Dict],
    dictionary_updates: Optional[List[Dict]] = None,
) -> Dict:
    """Apply a batch of proposed changes and optional dictionary updates."""

    model = parse_model_json(model_json_str)
    baseline_idx = {
        "entities": index_entities(model),
        "relationships": index_relationships(model),
    }

    applied: List[str] = []
    errors: List[str] = []

    for change in proposed_changes or []:
        success, message = apply_change(model, change, baseline_idx)
        if success:
            applied.append(message)
        else:
            errors.append(message)
        baseline_idx["entities"] = index_entities(model)
        baseline_idx["relationships"] = index_relationships(model)

    if dictionary_updates:
        apply_dictionary_updates(model, dictionary_updates)
        applied.append(f"Applied {len(dictionary_updates)} dictionary updates")

    return {
        "ok": not errors,
        "model_json": json.dumps(model, ensure_ascii=False, indent=2),
        "applied": applied,
        "errors": errors,
    }


__all__ = [
    "apply_change",
    "apply_changes",
    "apply_dictionary_updates",
    "index_entities",
    "index_relationships",
    "parse_model_json",
]
