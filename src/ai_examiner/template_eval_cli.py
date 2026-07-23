from __future__ import annotations

import argparse
import json
from pathlib import Path

from .template_engine.evaluation import evaluate_builtin_templates


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic v0.8 scenario-template release gates."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./data/template-evaluation-report.json"),
    )
    parser.add_argument("--performance-samples", type=int, default=25)
    parser.add_argument(
        "--provider-probe",
        action="append",
        type=Path,
        default=[],
        help="Optional template-provider-probe-v1 JSON evidence; may be repeated.",
    )
    parser.add_argument(
        "--require-release-evidence",
        action="store_true",
        help="Fail while provider, Docker or Vultr evidence remains held.",
    )
    return parser


def run_template_evaluation() -> None:
    args = _parser().parse_args()
    provider_reports = [
        json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
        for path in args.provider_probe
    ]
    report = evaluate_builtin_templates(
        performance_samples=args.performance_samples,
        provider_probe_reports=provider_reports,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Template deterministic gates: "
        f"{report['deterministic_gates']['status']}"
    )
    print(f"Report: {output}")
    if report["deterministic_gates"]["status"] != "passed":
        raise SystemExit(1)
    if (
        args.require_release_evidence
        and report["release_evidence"]["status"] != "passed"
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    run_template_evaluation()
