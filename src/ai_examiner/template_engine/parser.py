from __future__ import annotations

import copy
import json
import math
from typing import Any

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

MAX_TEMPLATE_BYTES = 256 * 1024
MAX_TEMPLATE_DEPTH = 20
MAX_TEMPLATE_NODES = 5_000
MAX_COLLECTION_ITEMS = 1_000
MAX_STRING_LENGTH = 50_000


class TemplateParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise TemplateParseError(
                "TEMPLATE_IMPORT_UNSAFE", "Template object keys must be scalar"
            ) from exc
        if duplicate:
            raise TemplateParseError(
                "TEMPLATE_STRUCTURAL_INVALID", f"Duplicate template key: {key}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TemplateParseError(
                "TEMPLATE_STRUCTURAL_INVALID", f"Duplicate template key: {key}"
            )
        result[key] = value
    return result


def _bounded_walk(value: Any, *, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_TEMPLATE_NODES:
        raise TemplateParseError("TEMPLATE_IMPORT_TOO_LARGE", "Template has too many nodes")
    if depth > MAX_TEMPLATE_DEPTH:
        raise TemplateParseError("TEMPLATE_IMPORT_TOO_DEEP", "Template nesting is too deep")
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise TemplateParseError(
                "TEMPLATE_IMPORT_TOO_LARGE", "Template object has too many entries"
            )
        for key, item in value.items():
            if not isinstance(key, str):
                raise TemplateParseError(
                    "TEMPLATE_IMPORT_UNSAFE", "Template object keys must be strings"
                )
            if len(key) > 200:
                raise TemplateParseError(
                    "TEMPLATE_IMPORT_TOO_LARGE", "Template object key is too long"
                )
            _bounded_walk(item, depth=depth + 1, counter=counter)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise TemplateParseError(
                "TEMPLATE_IMPORT_TOO_LARGE", "Template list has too many entries"
            )
        for item in value:
            _bounded_walk(item, depth=depth + 1, counter=counter)
    elif isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise TemplateParseError(
                "TEMPLATE_IMPORT_TOO_LARGE", "Template string is too long"
            )
    elif isinstance(value, float) and not math.isfinite(value):
        raise TemplateParseError(
            "TEMPLATE_IMPORT_UNSAFE", "Template numbers must be finite"
        )
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise TemplateParseError(
            "TEMPLATE_IMPORT_UNSAFE", f"Unsupported template value type: {type(value).__name__}"
        )


def _decode(payload: str | bytes) -> str:
    if isinstance(payload, bytes):
        if len(payload) > MAX_TEMPLATE_BYTES:
            raise TemplateParseError("TEMPLATE_IMPORT_TOO_LARGE", "Template exceeds 256 KiB")
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TemplateParseError(
                "TEMPLATE_IMPORT_UNSAFE", "Template must be UTF-8"
            ) from exc
    if len(payload.encode("utf-8")) > MAX_TEMPLATE_BYTES:
        raise TemplateParseError("TEMPLATE_IMPORT_TOO_LARGE", "Template exceeds 256 KiB")
    return payload


def parse_template_document(payload: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = copy.deepcopy(payload)
        _bounded_walk(data)
        return data

    text = _decode(payload)
    try:
        if text.lstrip().startswith("{"):
            data = json.loads(text, object_pairs_hook=_unique_json_object)
        else:
            for event in yaml.parse(text):
                if isinstance(event, AliasEvent):
                    raise TemplateParseError(
                        "TEMPLATE_IMPORT_UNSAFE", "YAML aliases are not supported"
                    )
            data = yaml.load(text, Loader=_UniqueKeyLoader)
    except TemplateParseError:
        raise
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise TemplateParseError(
            "TEMPLATE_STRUCTURAL_INVALID", f"Template could not be parsed: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise TemplateParseError(
            "TEMPLATE_STRUCTURAL_INVALID", "Template root must be an object"
        )
    _bounded_walk(data)
    return data
