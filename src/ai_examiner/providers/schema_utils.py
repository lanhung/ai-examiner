from __future__ import annotations

import re
from typing import Any

from json_repair import repair_json


def schema_name(agent: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", agent).strip("_")
    return (cleaned or "structured_response")[:64]


def hint_to_json_schema(value: Any) -> dict[str, Any]:
    """Convert the project's compact example-shaped hints into strict JSON Schema."""
    if isinstance(value, dict):
        properties = {key: hint_to_json_schema(item) for key, item in value.items()}
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        item = value[0] if value else "string"
        return {"type": "array", "items": hint_to_json_schema(item)}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str) and "|" in value:
        choices = [item.strip() for item in value.split("|") if item.strip()]
        if len(choices) > 1 and all(re.fullmatch(r"[a-zA-Z0-9_-]+", item) for item in choices):
            return {"type": "string", "enum": choices}
    return {"type": "string"}


def parse_json_object(text: str) -> dict[str, Any]:
    import json

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    candidate = cleaned if start < 0 or end <= start else cleaned[start : end + 1]
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError as error:
        if start < 0:
            raise ValueError("Model did not return a JSON object") from None
        try:
            result = repair_json(candidate, return_objects=True, skip_json_loads=True)
        except Exception as repair_error:
            raise ValueError(
                f"Model returned malformed JSON at line {error.lineno}, "
                f"column {error.colno}, and repair failed: {repair_error}"
            ) from None
    if not isinstance(result, dict):
        raise ValueError("Model returned JSON, but not an object")
    return result
