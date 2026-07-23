from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .agents.base import AgentContext
from .agents.planner import SessionPlanner
from .config import Settings, get_settings
from .providers.base import ProviderResult
from .providers.factory import build_provider, parse_profile, profile_ready
from .template_engine.compiler import TemplateCompiler
from .template_engine.evaluation import latest_builtin_sources

TEMPLATE_PROVIDER_PROBE_VERSION = "template-provider-probe-v1"
DEFAULT_TEMPLATE_SLUGS = (
    "academic.thesis_defense",
    "education.course_oral",
    "engineering.technical_interview",
)


def _usage_recorder(target: list[dict[str, Any]]):
    def record_usage(agent: str, result: ProviderResult) -> None:
        target.append(
            {
                "agent": agent,
                "provider": result.provider,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
                "retry_count": result.retry_count,
                "json_repair_used": result.json_repair_used,
            }
        )

    return record_usage


def _validate_blueprint(blueprint: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    questions = blueprint.get("questions") or []
    selection = contract["question_selection"]
    allowed_types = set(selection["allowed_types"])
    objectives = {
        item["id"] for item in contract["planner"]["objectives"]
    }
    minimum = int(selection["difficulty"]["minimum"])
    maximum = int(selection["difficulty"]["maximum"])
    if not questions:
        return ["no_questions"]
    if len(questions) > int(selection["question_limit"]):
        violations.append("question_limit_exceeded")
    for index, question in enumerate(questions):
        prefix = f"question_{index + 1}"
        if question.get("type") not in allowed_types:
            violations.append(f"{prefix}_type_outside_allowlist")
        if not minimum <= int(question.get("difficulty", 0)) <= maximum:
            violations.append(f"{prefix}_difficulty_outside_bounds")
        mapped = set(question.get("objective_ids") or [])
        if not mapped or not mapped <= objectives:
            violations.append(f"{prefix}_objective_mapping_invalid")
        if not question.get("expected_points"):
            violations.append(f"{prefix}_expected_points_missing")
        if not str(question.get("source_excerpt") or "").strip():
            violations.append(f"{prefix}_source_excerpt_missing")
    return violations


def run_provider_probe(
    *,
    settings: Settings,
    profiles: list[str],
    template_slugs: list[str],
    document_text: str,
    filename: str,
    language: str,
) -> dict[str, Any]:
    sources = latest_builtin_sources()
    missing = sorted(set(template_slugs) - set(sources))
    if missing:
        raise ValueError(f"Unknown built-in template slugs: {', '.join(missing)}")

    results: list[dict[str, Any]] = []
    for profile in profiles:
        parse_profile(profile)
        if not profile_ready(settings, profile):
            results.append(
                {
                    "profile": profile,
                    "status": "not_configured",
                    "template_results": [],
                }
            )
            continue
        provider = build_provider(settings, profile)
        profile_results: list[dict[str, Any]] = []
        for slug in template_slugs:
            source = sources[slug]
            compiled = TemplateCompiler().compile(source)
            usage: list[dict[str, Any]] = []

            try:
                blueprint = SessionPlanner(
                    AgentContext(
                        provider=provider,
                        record_usage=_usage_recorder(usage),
                    )
                ).plan(
                    document_text=document_text,
                    filename=filename,
                    language=language,
                    template_contract=compiled.compiled,
                )
                violations = _validate_blueprint(blueprint, compiled.compiled)
                profile_results.append(
                    {
                        "slug": slug,
                        "semantic_version": source["template"]["version"],
                        "fingerprint": compiled.fingerprint,
                        "status": "passed" if not violations else "failed",
                        "question_count": len(blueprint.get("questions") or []),
                        "question_types": [
                            item.get("type")
                            for item in blueprint.get("questions") or []
                        ],
                        "coverage": (blueprint.get("template_plan") or {}).get(
                            "coverage"
                        ),
                        "violations": violations,
                        "usage": usage,
                    }
                )
            except Exception as exc:
                profile_results.append(
                    {
                        "slug": slug,
                        "semantic_version": source["template"]["version"],
                        "fingerprint": compiled.fingerprint,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "usage": usage,
                    }
                )
        results.append(
            {
                "profile": profile,
                "status": (
                    "passed"
                    if all(item["status"] == "passed" for item in profile_results)
                    else "failed"
                ),
                "template_results": profile_results,
            }
        )

    configured_results = [
        item for item in results if item["status"] != "not_configured"
    ]
    return {
        "probe_version": TEMPLATE_PROVIDER_PROBE_VERSION,
        "scope": "provider_contract_probe_not_scenario_relevance_judging",
        "language": language,
        "filename": filename,
        "profiles": profiles,
        "template_slugs": template_slugs,
        "sample_counts": {
            "profiles_requested": len(profiles),
            "profiles_configured": len(configured_results),
            "template_runs": sum(
                len(item["template_results"]) for item in configured_results
            ),
        },
        "status": (
            "passed"
            if configured_results
            and all(item["status"] == "passed" for item in configured_results)
            else "failed"
        ),
        "results": results,
        "limitations": [
            "This probe verifies provider access and compiled-contract compliance.",
            "It does not measure relevance improvement or replace blind judging.",
            "It does not authorize a v0.8 release candidate.",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe real providers against v0.8 compiled template contracts."
    )
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("./data/template-provider-probe.json"))
    parser.add_argument(
        "--profiles",
        default="qwen:qwen-plus,openai:gpt-5.4-mini",
    )
    parser.add_argument(
        "--templates",
        default=",".join(DEFAULT_TEMPLATE_SLUGS),
    )
    parser.add_argument("--language", default="zh-CN")
    return parser


def run_template_provider_probe() -> None:
    args = _parser().parse_args()
    document = args.document.expanduser().resolve()
    if not document.is_file():
        raise SystemExit(f"Document does not exist: {document}")
    profiles = [item.strip() for item in args.profiles.split(",") if item.strip()]
    template_slugs = [
        item.strip() for item in args.templates.split(",") if item.strip()
    ]
    report = run_provider_probe(
        settings=get_settings(),
        profiles=profiles,
        template_slugs=template_slugs,
        document_text=document.read_text(encoding="utf-8"),
        filename=document.name,
        language=args.language,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Template provider probe: {report['status']}")
    print(f"Report: {output}")
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    run_template_provider_probe()
