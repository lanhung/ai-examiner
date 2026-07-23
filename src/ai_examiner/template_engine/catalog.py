from __future__ import annotations

from typing import Any

from ..templates.builtin import load_builtin_template
from .compiler import TEMPLATE_COMPILER_VERSION, TemplateCompiler
from .validator import TEMPLATE_VALIDATOR_VERSION, validate_template

BUILTIN_TEMPLATE_FILES = (
    "academic.thesis_defense.v1.yaml",
    "academic.thesis_defense.v1_1.yaml",
)


def _localized(value: dict[str, str]) -> dict[str, str]:
    return {language: value[language] for language in sorted(value)}


def builtin_template_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    compiler = TemplateCompiler()
    for filename in BUILTIN_TEMPLATE_FILES:
        raw = load_builtin_template(filename)
        validation = validate_template(raw)
        issues = [issue.model_dump(mode="json") for issue in validation.issues]
        if not validation.valid or validation.source is None:
            catalog.append(
                {
                    "source": filename,
                    "valid": False,
                    "issues": issues,
                    "validator_version": TEMPLATE_VALIDATOR_VERSION,
                    "compiler_version": TEMPLATE_COMPILER_VERSION,
                }
            )
            continue

        source = validation.source
        compiled = compiler.compile(source)
        metadata = source.template
        catalog.append(
            {
                "source": filename,
                "slug": metadata.slug,
                "version": metadata.version,
                "category": metadata.category,
                "title": _localized(metadata.title.root),
                "description": _localized(metadata.description.root),
                "trust_level": metadata.trust_level,
                "intended_use": metadata.intended_use,
                "risk_tier": metadata.risk_tier,
                "capabilities": source.capabilities.model_dump(mode="json"),
                "fingerprint": compiled.fingerprint,
                "schema_version": source.schema_version,
                "validator_version": TEMPLATE_VALIDATOR_VERSION,
                "compiler_version": TEMPLATE_COMPILER_VERSION,
                "valid": True,
                "issues": issues,
            }
        )
    return sorted(
        catalog,
        key=lambda item: (item.get("slug", ""), item.get("version", ""), item["source"]),
    )


def builtin_template_health() -> dict[str, Any]:
    templates = builtin_template_catalog()
    valid_count = sum(item["valid"] for item in templates)
    invalid = [
        {"source": item["source"], "issues": item["issues"]}
        for item in templates
        if not item["valid"]
    ]
    return {
        "status": "ok" if not invalid else "degraded",
        "template_count": len(templates),
        "valid_count": valid_count,
        "invalid_count": len(invalid),
        "validator_version": TEMPLATE_VALIDATOR_VERSION,
        "compiler_version": TEMPLATE_COMPILER_VERSION,
        "invalid_templates": invalid,
    }


__all__ = [
    "BUILTIN_TEMPLATE_FILES",
    "builtin_template_catalog",
    "builtin_template_health",
]
