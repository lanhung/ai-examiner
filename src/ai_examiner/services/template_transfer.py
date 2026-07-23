from __future__ import annotations

import copy
import json
from typing import Any, Literal

import yaml
from sqlalchemy.orm import Session

from ..models import ScenarioTemplate, ScenarioTemplateVersion
from ..template_engine.parser import TemplateParseError, parse_template_document
from .templates import TemplateLifecycleError, TemplateLifecycleService

TEMPLATE_EXPORT_VERSION = "template-export-v1"
DIFF_GROUPS = (
    "template",
    "capabilities",
    "objectives",
    "question_policy",
    "assistance_policy",
    "conversation_policy",
    "assessment_policy",
    "report_policy",
    "safety_policy",
    "presentation_policy",
    "voice_policy",
    "compatibility",
    "overrides",
)
BEHAVIOR_GROUPS = frozenset(DIFF_GROUPS) - {"template"}


def _metadata(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("template")
    if not isinstance(metadata, dict):
        raise TemplateLifecycleError(
            "TEMPLATE_SOURCE_INVALID",
            "Imported template must contain template metadata",
            status_code=422,
        )
    return metadata


def import_template_document(
    db: Session,
    *,
    document: str | dict[str, Any],
    target_slug: str | None = None,
    semantic_version: str | None = None,
) -> tuple[ScenarioTemplate, ScenarioTemplateVersion]:
    try:
        source = parse_template_document(document)
    except TemplateParseError as exc:
        raise TemplateLifecycleError(exc.code, str(exc), status_code=422) from exc
    metadata = _metadata(source)
    slug = str(target_slug or metadata.get("slug") or "")
    version = str(semantic_version or metadata.get("version") or "")
    category = str(metadata.get("category") or "")
    if not slug or not version or not category:
        raise TemplateLifecycleError(
            "TEMPLATE_SOURCE_INVALID",
            "Imported template metadata requires slug, version and category",
            status_code=422,
        )
    return TemplateLifecycleService(db).create_local(
        slug=slug,
        category=category,
        semantic_version=version,
        source=source,
    )


def export_template_document(
    version: ScenarioTemplateVersion,
    *,
    output_format: Literal["json", "yaml"],
) -> tuple[bytes, str]:
    source = copy.deepcopy(version.source_json)
    if output_format == "json":
        payload = json.dumps(
            source,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ).encode("utf-8")
        return payload, "application/json; charset=utf-8"
    payload = yaml.safe_dump(
        source,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).encode("utf-8")
    return payload, "application/yaml; charset=utf-8"


def _pointer(path: tuple[str, ...]) -> str:
    return "/" + "/".join(
        part.replace("~", "~0").replace("/", "~1") for part in path
    )


def _changes(
    before: Any,
    after: Any,
    *,
    path: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child_path = (*path, str(key))
            if key not in before:
                changes.append(
                    {
                        "kind": "added",
                        "path": _pointer(child_path),
                        "before": None,
                        "after": copy.deepcopy(after[key]),
                    }
                )
            elif key not in after:
                changes.append(
                    {
                        "kind": "removed",
                        "path": _pointer(child_path),
                        "before": copy.deepcopy(before[key]),
                        "after": None,
                    }
                )
            else:
                changes.extend(
                    _changes(before[key], after[key], path=child_path)
                )
        return changes
    if before == after:
        return []
    return [
        {
            "kind": "changed",
            "path": _pointer(path),
            "before": copy.deepcopy(before),
            "after": copy.deepcopy(after),
        }
    ]


def semantic_template_diff(
    left: ScenarioTemplateVersion,
    right: ScenarioTemplateVersion,
) -> dict[str, Any]:
    left_source = left.source_json or {}
    right_source = right.source_json or {}
    groups = []
    total_changes = 0
    behavioral_changes = 0
    for group_id in DIFF_GROUPS:
        changes = _changes(
            left_source.get(group_id),
            right_source.get(group_id),
            path=(group_id,),
        )
        if not changes:
            continue
        total_changes += len(changes)
        if group_id in BEHAVIOR_GROUPS:
            behavioral_changes += len(changes)
        groups.append(
            {
                "id": group_id,
                "behavioral": group_id in BEHAVIOR_GROUPS,
                "change_count": len(changes),
                "changes": changes,
            }
        )
    return {
        "diff_version": "template-semantic-diff-v1",
        "left": {
            "id": left.id,
            "template_id": left.template_id,
            "version": left.semantic_version,
            "fingerprint": left.fingerprint,
        },
        "right": {
            "id": right.id,
            "template_id": right.template_id,
            "version": right.semantic_version,
            "fingerprint": right.fingerprint,
        },
        "summary": {
            "identical": total_changes == 0,
            "change_count": total_changes,
            "behavioral_change_count": behavioral_changes,
            "changed_groups": [group["id"] for group in groups],
        },
        "groups": groups,
    }


__all__ = [
    "TEMPLATE_EXPORT_VERSION",
    "export_template_document",
    "import_template_document",
    "semantic_template_diff",
]
