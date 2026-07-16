from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import PromptVersion

DEFAULT_PROMPTS = {
    "planner": "Plan grounded oral-defense questions from the supplied material.",
    "answer_analyzer": "Analyze the answer against expected points and evidence.",
    "golden_annotator": "Create grounded and discriminative oral-defense cases.",
    "annotation_critic": "Adversarially audit generated cases for grounding and quality.",
    "consensus_synthesizer": "Merge candidates and critiques into a defensible dataset.",
    "visual_evidence": "Inspect page or slide evidence and generate grounded observations.",
    "joint_analysis": "Compare documents for alignment, omissions, and contradictions.",
}


def seed_prompt_registry(db: Session, prompt_dir: Path) -> None:
    existing = db.scalar(select(func.count(PromptVersion.id))) or 0
    if existing:
        return
    loaded: set[str] = set()
    for path in sorted(prompt_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = str(payload.get("name") or path.stem.split(".")[0])
        version = int(payload.get("version") or 1)
        loaded.add(name)
        db.add(
            PromptVersion(
                name=name,
                version=version,
                role=str(payload.get("role") or "general"),
                content=str(payload.get("content") or ""),
                metadata_json=payload.get("metadata") or {},
                status=str(payload.get("status") or "active"),
            )
        )
    for name, content in DEFAULT_PROMPTS.items():
        if name not in loaded:
            db.add(
                PromptVersion(
                    name=name,
                    version=1,
                    role=name,
                    content=content,
                    metadata_json={"seeded": True},
                    status="active",
                )
            )
    db.commit()


def active_prompt(db: Session, name: str) -> PromptVersion | None:
    return db.scalar(
        select(PromptVersion)
        .where(PromptVersion.name == name, PromptVersion.status == "active")
        .order_by(PromptVersion.version.desc())
    )


def prompt_manifest(db: Session) -> dict[str, str]:
    prompts = db.scalars(
        select(PromptVersion)
        .where(PromptVersion.status == "active")
        .order_by(PromptVersion.name, PromptVersion.version.desc())
    ).all()
    result: dict[str, str] = {}
    for prompt in prompts:
        result.setdefault(prompt.name, f"{prompt.name}:v{prompt.version}")
    return result



def prompt_contents(db: Session) -> dict[str, str]:
    rows = db.scalars(
        select(PromptVersion)
        .where(PromptVersion.status == "active")
        .order_by(PromptVersion.name, PromptVersion.version.desc())
    ).all()
    result: dict[str, str] = {}
    for row in rows:
        result.setdefault(row.name, row.content)
    return result


def create_prompt_version(
    db: Session,
    *,
    name: str,
    role: str,
    content: str,
    schema_hint: dict,
    metadata: dict,
    activate: bool,
) -> PromptVersion:
    version = (
        db.scalar(select(func.max(PromptVersion.version)).where(PromptVersion.name == name)) or 0
    ) + 1
    if activate:
        db.execute(
            update(PromptVersion)
            .where(PromptVersion.name == name, PromptVersion.status == "active")
            .values(status="candidate")
        )
    prompt = PromptVersion(
        name=name,
        version=version,
        role=role,
        content=content,
        schema_hint=schema_hint,
        metadata_json=metadata,
        status="active" if activate else "draft",
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def activate_prompt(db: Session, prompt: PromptVersion) -> PromptVersion:
    db.execute(
        update(PromptVersion)
        .where(PromptVersion.name == prompt.name, PromptVersion.status == "active")
        .values(status="candidate")
    )
    prompt.status = "active"
    db.commit()
    db.refresh(prompt)
    return prompt
