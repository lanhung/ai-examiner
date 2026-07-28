from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
from pathlib import Path

from .config import get_settings
from .db import SessionLocal, init_db
from .models import Document, Project
from .providers.factory import parse_profile, profile_ready
from .services.documents import parse_document
from .services.evidence import persist_evidence
from .services.golden import GoldenDatasetService
from .services.storage import StorageService, document_object_key

SUPPORTED_SUFFIXES = {".pdf", ".pptx", ".docx", ".txt", ".md", ".markdown"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an AI-curated Golden Dataset corpus from a folder of papers. "
            "Each paper is independently annotated, cross-reviewed, synthesized, and exported."
        )
    )
    parser.add_argument("--input", required=True, type=Path, help="Folder containing papers")
    parser.add_argument("--output", type=Path, default=Path("./golden_exports"))
    parser.add_argument("--project-name", default="AI Golden Corpus")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument(
        "--profiles",
        default=None,
        help="Comma-separated provider:model profiles; defaults to GOLDEN_DEFAULT_PROFILES",
    )
    parser.add_argument("--consensus-profile", default=None)
    parser.add_argument("--question-count", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--stop-on-error", action="store_true")
    return parser


def _export_dataset(output_dir: Path, source: Path, dataset) -> tuple[Path, Path]:
    stem = source.stem.replace(" ", "_")
    full_path = output_dir / f"{stem}.golden.json"
    jsonl_path = output_dir / f"{stem}.golden.jsonl"
    full_payload = {
        "dataset_id": dataset.id,
        "name": dataset.name,
        "version": dataset.version,
        "status": dataset.status,
        "generator_profiles": dataset.generator_profiles,
        "consensus_profile": dataset.consensus_profile,
        "quality_metrics": dataset.quality_metrics,
        "data": dataset.data,
    }
    full_path.write_text(json.dumps(full_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for case in dataset.data.get("cases") or []:
            handle.write(
                json.dumps(
                    {
                        "dataset_id": dataset.id,
                        "source_file": source.name,
                        "generator_profiles": dataset.generator_profiles,
                        "consensus_profile": dataset.consensus_profile,
                        **case,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return full_path, jsonl_path


def build_corpus() -> None:
    args = _parser().parse_args()
    settings = get_settings()
    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    if not input_dir.is_dir():
        raise SystemExit(f"Input folder does not exist: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    profiles = [
        item.strip()
        for item in (args.profiles or settings.golden_default_profiles).split(",")
        if item.strip()
    ]
    if not profiles:
        profiles = ["mock:heuristic-v2"]
    for profile in profiles:
        parse_profile(profile)
        if not profile_ready(settings, profile):
            raise SystemExit(f"Profile is not configured: {profile}")
    consensus_profile = args.consensus_profile or profiles[0]
    parse_profile(consensus_profile)
    if not profile_ready(settings, consensus_profile):
        raise SystemExit(f"Consensus profile is not configured: {consensus_profile}")
    if consensus_profile not in profiles:
        profiles.append(consensus_profile)
    question_count = args.question_count or settings.golden_question_count
    if not 4 <= question_count <= 20:
        raise SystemExit("question-count must be between 4 and 20")

    papers = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )[: max(1, min(args.limit, 20))]
    if not papers:
        raise SystemExit("No supported PDF/PPTX/DOCX/TXT/Markdown files found")

    init_db()
    summary: dict = {
        "project_name": args.project_name,
        "profiles": profiles,
        "consensus_profile": consensus_profile,
        "question_count": question_count,
        "processed": [],
        "failed": [],
    }
    with SessionLocal() as db:
        project = Project(name=args.project_name, domain="research_defense", language=args.language)
        db.add(project)
        db.commit()
        db.refresh(project)
        project_upload_dir = settings.upload_dir / project.id
        project_upload_dir.mkdir(parents=True, exist_ok=True)

        for index, paper in enumerate(papers, start=1):
            print(f"[{index}/{len(papers)}] {paper.name}: parsing")
            try:
                raw = paper.read_bytes()
                destination = project_upload_dir / paper.name
                shutil.copy2(paper, destination)
                parsed = parse_document(
                    destination,
                    raw,
                    settings.max_document_chars,
                    evidence_output_dir=settings.evidence_dir / project.id / paper.stem,
                )
                document = Document(
                    organization_id=project.organization_id,
                    project_id=project.id,
                    filename=paper.name,
                    content_type=mimetypes.guess_type(paper.name)[0]
                    or "application/octet-stream",
                    storage_path=None,
                    content_text=parsed.text,
                    page_map=[
                        {
                            key: value
                            for key, value in page.items()
                            if key != "preview_path"
                        }
                        for page in parsed.page_map
                    ],
                    parse_warnings=parsed.warnings,
                    char_count=len(parsed.text),
                )
                db.add(document)
                db.flush()
                stored = StorageService(db, settings).store_bytes(
                    organization_id=project.organization_id,
                    project_id=project.id,
                    resource_type="document",
                    resource_id=document.id,
                    purpose="source",
                    object_key=document_object_key(
                        project.organization_id,
                        project.id,
                        document.id,
                        filename=document.filename,
                        content_type=document.content_type,
                    ),
                    data=raw,
                    content_type=document.content_type,
                )
                document.storage_object_id = stored.id
                persist_evidence(
                    db,
                    project_id=project.id,
                    document=document,
                    drafts=parsed.evidence,
                    settings=settings,
                )
                db.commit()
                db.refresh(document)
                print(f"[{index}/{len(papers)}] {paper.name}: multi-model annotation")
                dataset = GoldenDatasetService(db, settings, project.id, document).generate(
                    profiles=profiles,
                    consensus_profile=consensus_profile,
                    question_count=question_count,
                    language=args.language,
                )
                full_path, jsonl_path = _export_dataset(output_dir, paper, dataset)
                summary["processed"].append(
                    {
                        "source": paper.name,
                        "dataset_id": dataset.id,
                        "status": dataset.status,
                        "case_count": dataset.quality_metrics.get("case_count"),
                        "quality": dataset.quality_metrics,
                        "json": str(full_path),
                        "jsonl": str(jsonl_path),
                    }
                )
            except Exception as exc:
                db.rollback()
                summary["failed"].append({"source": paper.name, "error": str(exc)})
                print(f"[{index}/{len(papers)}] {paper.name}: FAILED: {exc}")
                if args.stop_on_error:
                    break

    summary["processed_count"] = len(summary["processed"])
    summary["failed_count"] = len(summary["failed"])
    summary_path = output_dir / "corpus-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Corpus complete: {summary['processed_count']} processed, {summary['failed_count']} failed")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    build_corpus()
