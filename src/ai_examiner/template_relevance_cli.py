from __future__ import annotations

import argparse
import json
from pathlib import Path

from .template_engine.relevance import (
    evaluate_relevance_reports,
    expand_relevance_corpus,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export the frozen v0.8 scenario corpus or aggregate independent "
            "blind-judge reports."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./data/template-relevance-report.json"),
    )
    parser.add_argument(
        "--export-corpus",
        type=Path,
        help="Write the expanded, fingerprinted frozen corpus to this path.",
    )
    parser.add_argument(
        "--judge-report",
        action="append",
        type=Path,
        default=[],
        help="A template-relevance-judge-v1 JSON report; may be repeated.",
    )
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="Exit 2 unless at least three complete template evaluations pass.",
    )
    return parser


def run_template_relevance_evaluation() -> None:
    args = _parser().parse_args()
    if args.export_corpus:
        corpus_path = args.export_corpus.expanduser().resolve()
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        corpus_path.write_text(
            json.dumps(expand_relevance_corpus(), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(f"Frozen corpus: {corpus_path}")

    reports = [
        json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
        for path in args.judge_report
    ]
    result = evaluate_relevance_reports(reports)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Template relevance evidence: {result['status']}")
    print(f"Frozen cases: {result['corpus']['case_count']}")
    print(f"Report: {output}")
    if args.require_pass and result["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    run_template_relevance_evaluation()
