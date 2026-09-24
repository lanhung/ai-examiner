"""ai-examiner-quality-lab: large-scale multi-domain quality and cost evaluation.

Examples
--------
Offline smoke run (no API keys, heuristic judge)::

    ai-examiner-quality-lab run --planner mock:heuristic-v2 --analyzer mock:heuristic-v2

Real comparison on a host with keys in .env::

    ai-examiner-quality-lab run \\
        --planner qwen:qwen-plus --planner openai:gpt-5.4-mini \\
        --analyzer qwen:qwen-plus --analyzer qwen:qwen-turbo --analyzer openai:gpt-5.4-mini \\
        --judge anthropic:claude-sonnet-5 --learner qwen:qwen-plus \\
        --price qwen:qwen-turbo=0.05,0.2 --max-cost-usd 20 --out runs/2026-09-lab

    ai-examiner-quality-lab report runs/2026-09-lab
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .corpus import load_corpus
from .personas import PERSONAS


def _split(values: list[str] | None) -> list[str]:
    items: list[str] = []
    for value in values or []:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return list(dict.fromkeys(items))


def _prices(values: list[str] | None) -> dict[str, tuple[float, float]]:
    prices = {}
    for value in values or []:
        profile, _, rates = value.partition("=")
        input_rate, _, output_rate = rates.partition(",")
        prices[profile.strip()] = (float(input_rate), float(output_rate))
    return prices


def _prepare_environment(out_dir: Path, database_url: str | None) -> None:
    out = out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    forced = {
        "DATABASE_URL": database_url or f"sqlite:///{(out / 'lab.db').as_posix()}",
        "AUTH_MODE": "disabled",
        "APP_ENV": "development",
        "MODEL_RATE_LIMIT_BACKEND": "memory",
        "MODEL_RATE_LIMIT_REQUIRED": "false",
        "CELERY_ALWAYS_EAGER": "true",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_ROOT": str(out / "objects"),
        "UPLOAD_DIR": str(out / "uploads"),
        "EVIDENCE_DIR": str(out / "evidence"),
        "EXPORT_DIR": str(out / "exports"),
        "DAILY_MODEL_BUDGET_USD": "1000000",
        "PROJECT_MODEL_BUDGET_USD": "1000000",
    }
    os.environ.update(forced)
    os.environ.setdefault("MEMORY_IDENTITY_SECRET", "quality-lab-local-only-secret")
    repo_prompts = Path(__file__).resolve().parents[3] / "prompts"
    if "PROMPT_DIR" not in os.environ and repo_prompts.is_dir():
        os.environ["PROMPT_DIR"] = str(repo_prompts)


def widen_lab_model_policy(session_factory, profiles: list[str]) -> None:
    """Allow the profiles under test in the lab's private database only."""
    from ..enterprise_constants import LEGACY_ORGANIZATION_ID
    from ..providers.factory import parse_profile
    from ..services import model_governance

    with session_factory() as db:
        policy = model_governance.ensure_model_policy(db, LEGACY_ORGANIZATION_ID)
        allowed = list(policy.allowed_profiles_json or [])
        present = {(item.get("provider"), item.get("model_pattern")) for item in allowed}
        for profile in profiles:
            provider, model = parse_profile(profile)
            if (provider, model) not in present:
                allowed.append({"provider": provider, "model_pattern": model, "tasks": ["*"]})
        policy.allowed_profiles_json = allowed
        policy.external_provider_max_classification = "restricted"
        policy.monthly_budget_usd = 1_000_000.0
        policy.per_session_budget_usd = 1_000.0
        policy.per_request_budget_usd = 100.0
        policy.organization_requests_per_minute = 100_000
        policy.principal_requests_per_minute = 100_000
        policy.organization_tokens_per_minute = 100_000_000
        policy.policy_digest = model_governance._effective_policy_digest(policy)
        db.commit()


def _summarize(
    paths: list[Path],
    *,
    learners_per_blueprint: int,
    tolerance: float,
    heuristic: bool | None,
    out_dir: Path,
) -> dict:
    from .metrics import aggregate
    from .report import render_markdown
    from .runner import load_results

    records = load_results(paths)
    summary = aggregate(
        records,
        learners_per_blueprint=learners_per_blueprint,
        tolerance=tolerance,
    )
    if heuristic is None:
        heuristic = any(
            rating.get("comment") == "heuristic judge"
            for record in records
            for rating in record.get("ratings", [])
        )
    summary["heuristic_judge"] = heuristic
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(
        render_markdown(summary, heuristic_judge=heuristic), encoding="utf-8"
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-examiner-quality-lab", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the evaluation matrix")
    run.add_argument("--planner", action="append", help="question-generation profile(s)")
    run.add_argument("--analyzer", action="append", help="answer-analysis profile(s)")
    run.add_argument("--judge", default="mock:heuristic-v2",
                     help="independent judge profile; mock uses the offline heuristic")
    run.add_argument("--learner", default=None,
                     help="LLM profile for simulated learners (default: rule-based)")
    run.add_argument("--personas", action="append", help=f"subset of {sorted(PERSONAS)}")
    run.add_argument("--materials", action="append", help="material ids or domains")
    run.add_argument("--corpus-dir", action="append", type=Path, default=[],
                     help="extra directories of *.md materials with front matter")
    run.add_argument("--no-builtin", action="store_true")
    run.add_argument("--question-limit", type=int, default=3)
    run.add_argument("--max-followups", type=int, default=1)
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--judge-fraction", type=float, default=1.0)
    run.add_argument("--max-cost-usd", type=float, default=None)
    run.add_argument("--learners-per-blueprint", type=int, default=30)
    run.add_argument("--tolerance", type=float, default=0.03)
    run.add_argument("--price", action="append",
                     help="override USD per million tokens: provider:model=input,output")
    run.add_argument("--shard", default="0/1", help="i/n to split materials across processes")
    run.add_argument("--out", type=Path, default=Path("quality_lab_results"))
    run.add_argument("--database-url", default=None)

    report = commands.add_parser("report", help="aggregate one or more result directories")
    report.add_argument("paths", nargs="+", type=Path)
    report.add_argument("--out", type=Path, default=None)
    report.add_argument("--learners-per-blueprint", type=int, default=30)
    report.add_argument("--tolerance", type=float, default=0.03)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "report":
        out_dir = args.out or args.paths[0]
        summary = _summarize(
            args.paths,
            learners_per_blueprint=args.learners_per_blueprint,
            tolerance=args.tolerance,
            heuristic=None,
            out_dir=out_dir,
        )
        print(json.dumps(summary["recommendation"], ensure_ascii=False, indent=2))
        print(f"Report: {out_dir / 'report.md'}")
        return 0

    planners = _split(args.planner) or ["mock:heuristic-v2"]
    analyzers = _split(args.analyzer) or ["mock:heuristic-v2"]
    personas = _split(args.personas) or list(PERSONAS)
    unknown = sorted(set(personas) - set(PERSONAS))
    if unknown:
        print(f"Unknown personas: {unknown}", file=sys.stderr)
        return 2
    materials = load_corpus(
        args.corpus_dir,
        include_builtin=not args.no_builtin,
        only=set(_split(args.materials)) or None,
    )
    if not materials:
        print("No materials selected", file=sys.stderr)
        return 2
    if args.judge in planners + analyzers and not args.judge.startswith("mock:"):
        print(
            "warning: the judge is also under test; self-preference bias is likely. "
            "Prefer a judge from a different model family.",
            file=sys.stderr,
        )
    shard_index, _, shard_count = args.shard.partition("/")

    _prepare_environment(args.out, args.database_url)
    from fastapi.testclient import TestClient

    from ..config import get_settings
    from ..db import SessionLocal
    from ..main import app
    from ..providers.factory import build_provider
    from .runner import LabConfig, QualityLab

    settings = get_settings()
    config = LabConfig(
        materials=materials,
        planner_profiles=planners,
        analyzer_profiles=analyzers,
        judge_profile=args.judge,
        learner_profile=args.learner,
        personas=personas,
        question_limit=args.question_limit,
        max_followups=args.max_followups,
        repeats=args.repeats,
        judge_fraction=args.judge_fraction,
        max_cost_usd=args.max_cost_usd,
        learners_per_blueprint=args.learners_per_blueprint,
        price_overrides=_prices(args.price),
        shard_index=int(shard_index),
        shard_count=int(shard_count or 1),
        out_dir=args.out,
    )
    with TestClient(app) as client:
        widen_lab_model_policy(SessionLocal, planners + analyzers)
        lab = QualityLab(
            config,
            client,
            session_factory=SessionLocal,
            provider_factory=lambda profile: build_provider(settings, profile),
        )
        outcome = lab.run()
    summary = _summarize(
        [args.out],
        learners_per_blueprint=args.learners_per_blueprint,
        tolerance=args.tolerance,
        heuristic=args.judge.startswith("mock:") or None,
        out_dir=args.out,
    )
    print(json.dumps({**outcome, "recommendation": summary["recommendation"]},
                     ensure_ascii=False, indent=2))
    print(f"Report: {args.out / 'report.md'}")
    return 0


def run_quality_lab() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run_quality_lab()
