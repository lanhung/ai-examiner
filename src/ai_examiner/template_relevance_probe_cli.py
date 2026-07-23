from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import get_settings
from .template_engine.relevance import CASES_PER_TEMPLATE
from .template_engine.relevance_probe import (
    DEFAULT_RELEVANCE_TEMPLATES,
    run_relevance_probe,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate matched template artifacts and score them with an independent "
            "blind provider."
        )
    )
    parser.add_argument(
        "--generator-profile",
        default="qwen:qwen-plus",
    )
    parser.add_argument(
        "--judge-profile",
        default="openai:gpt-5.4-mini",
    )
    parser.add_argument(
        "--templates",
        default=",".join(DEFAULT_RELEVANCE_TEMPLATES),
    )
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument(
        "--cases-per-template",
        type=int,
        default=CASES_PER_TEMPLATE,
    )
    parser.add_argument(
        "--generation-path",
        choices=["session_planner", "batched_contract_probe"],
        default="session_planner",
        help="Only session_planner output is accepted as release evidence.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./data/template-relevance-probe.json"),
    )
    return parser


def run_template_relevance_probe() -> None:
    args = _parser().parse_args()
    template_slugs = [
        item.strip() for item in args.templates.split(",") if item.strip()
    ]
    report = run_relevance_probe(
        settings=get_settings(),
        generator_profile=args.generator_profile,
        judge_profile=args.judge_profile,
        template_slugs=template_slugs,
        batch_size=args.batch_size,
        cases_per_template=args.cases_per_template,
        generation_path=args.generation_path,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Template relevance probe: {len(report['evaluations'])} cases")
    print(f"Generator: {report['generator_profile']}")
    print(f"Blind judge: {report['judge_profile']}")
    print(f"Report: {output}")


if __name__ == "__main__":
    run_template_relevance_probe()
