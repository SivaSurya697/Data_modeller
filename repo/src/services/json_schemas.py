"""JSON Schema definitions and validation utilities for model drafting."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

__all__ = ["MODEL_SCHEMA", "validate_against_schema"]

MODEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["entities", "relationships", "dictionary", "shared_dim_refs"],
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "role", "attributes", "keys"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "role": {
                        "type": "string",
                        "enum": ["fact", "dimension", "other"],
                    },
                    "description": {"type": "string"},
                    "documentation": {"type": "string"},
                    "grain_json": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "uniqueItems": False,
                    },
                    "scd_type": {
                        "type": "string",
                        "enum": ["none", "scd1", "scd2"],
                    },
                    "attributes": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": [
                                "name",
                                "datatype",
                                "semantic_type",
                                "required",
                            ],
                            "properties": {
                                "name": {"type": "string", "minLength": 1},
                                "datatype": {"type": "string", "minLength": 1},
                                "semantic_type": {"type": "string", "minLength": 1},
                                "required": {"type": "boolean"},
                                "description": {"type": "string"},
                                "is_measure": {"type": "boolean"},
                                "is_surrogate_key": {"type": "boolean"},
                            },
                            "additionalProperties": True,
                        },
                    },
                    "keys": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["type", "columns"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["primary", "natural"],
                                },
                                "columns": {
                                    "type": "array",
                                    "items": {"type": "string", "minLength": 1},
                                    "minItems": 1,
                                },
                            },
                            "additionalProperties": True,
                        },
                    },
                    "is_shared_dim": {"type": "boolean"},
                },
                "additionalProperties": True,
                "allOf": [
                    {
                        "if": {
                            "properties": {"role": {"const": "fact"}},
                            "required": ["role"],
                        },
                        "then": {
                            "required": ["grain_json"],
                            "properties": {
                                "grain_json": {
                                    "type": "array",
                                    "items": {"type": "string", "minLength": 1},
                                    "minItems": 1,
                                },
                                "attributes": {
                                    "contains": {
                                        "type": "object",
                                        "properties": {
                                            "is_measure": {"const": True}
                                        },
                                        "required": ["is_measure"],
                                    }
                                },
                            },
                        },
                    },
                    {
                        "if": {
                            "properties": {"role": {"const": "dimension"}},
                            "required": ["role"],
                        },
                        "then": {
                            "required": ["scd_type"],
                            "properties": {
                                "scd_type": {
                                    "type": "string",
                                    "enum": ["none", "scd1", "scd2"],
                                }
                            },
                        },
                    },
                ],
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from", "to", "type", "rule"],
                "properties": {
                    "from": {"type": "string", "minLength": 1},
                    "to": {"type": "string", "minLength": 1},
                    "type": {
                        "type": "string",
                        "enum": [
                            "one_to_one",
                            "one_to_many",
                            "many_to_one",
                            "many_to_many",
                        ],
                    },
                    "rule": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "dictionary": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["term", "definition"],
                "properties": {
                    "term": {"type": "string", "minLength": 1},
                    "definition": {"type": "string", "minLength": 1},
                },
                "additionalProperties": True,
            },
        },
        "shared_dim_refs": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
    },
    "additionalProperties": True,
}

_VALIDATOR = Draft7Validator(MODEL_SCHEMA)


def _build_pointer(path: Sequence[Any]) -> str:
    if not path:
        return "/"
    tokens: list[str] = []
    for part in path:
        text = str(part)
        text = text.replace("~", "~0").replace("/", "~1")
        tokens.append(text)
    return "/" + "/".join(tokens)


def _format_required_error(error: ValidationError) -> Iterable[str]:
    instance_keys = set()
    if isinstance(error.instance, dict):
        instance_keys = set(error.instance.keys())
    missing: list[str] = []
    validator_value = error.validator_value
    if isinstance(validator_value, Sequence):
        missing = [
            str(field)
            for field in validator_value
            if str(field) not in instance_keys
        ]
    if not missing:
        message = error.message
        if "'" in message:
            parts = message.split("'")
            if len(parts) >= 3:
                missing = [parts[1]]
    base_path = list(error.absolute_path)
    for field in missing or ["<unknown>"]:
        pointer = _build_pointer(base_path + [field])
        yield f"{pointer} is required"


def validate_against_schema(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate *payload* against :data:`MODEL_SCHEMA`.

    Returns a tuple of ``(ok, errors)`` with JSON Pointer formatted messages.
    """

    if not isinstance(payload, dict):
        return False, ["/ payload must be a JSON object"]

    errors: list[str] = []
    for error in _VALIDATOR.iter_errors(payload):
        if error.validator == "required":
            errors.extend(_format_required_error(error))
            continue
        if error.validator == "contains":
            path = list(error.absolute_path)
            pointer = _build_pointer(path[:-1]) if path else "/"
            if pointer == "/":
                pointer = _build_pointer(path)
            errors.append(
                f"{pointer}: fact must have at least one attribute with is_measure=true"
            )
            continue
        pointer = _build_pointer(list(error.absolute_path))
        message = error.message
        if pointer:
            errors.append(f"{pointer} {message}")
        else:
            errors.append(message)

    return (not errors, errors)
