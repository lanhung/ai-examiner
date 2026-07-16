from __future__ import annotations

import difflib

from sqlalchemy.orm import Session

from ..models import GoldenDataset

ALLOWED_STATES = {"draft", "candidate", "frozen", "deprecated", "ready", "needs_review"}


def set_dataset_status(db: Session, dataset: GoldenDataset, status: str) -> GoldenDataset:
    if status not in ALLOWED_STATES:
        raise ValueError(f"Unsupported dataset status: {status}")
    dataset.status = status
    db.commit()
    db.refresh(dataset)
    return dataset


def dataset_diff(left: GoldenDataset, right: GoldenDataset) -> dict:
    left_cases = {case.get("id"): case for case in left.data.get("cases") or []}
    right_cases = {case.get("id"): case for case in right.data.get("cases") or []}
    added = sorted(set(right_cases) - set(left_cases))
    removed = sorted(set(left_cases) - set(right_cases))
    modified = []
    for case_id in sorted(set(left_cases) & set(right_cases)):
        before = left_cases[case_id]
        after = right_cases[case_id]
        changes = {}
        for field in ("question", "ideal_answer", "required_points", "followups", "common_errors"):
            if before.get(field) != after.get(field):
                before_text = str(before.get(field) or "")
                after_text = str(after.get(field) or "")
                changes[field] = {
                    "before": before.get(field),
                    "after": after.get(field),
                    "similarity": round(difflib.SequenceMatcher(None, before_text, after_text).ratio(), 3),
                }
        if changes:
            modified.append({"case_id": case_id, "changes": changes})
    return {
        "left": {"id": left.id, "version": left.version, "status": left.status},
        "right": {"id": right.id, "version": right.version, "status": right.status},
        "added": added,
        "removed": removed,
        "modified": modified,
        "summary": {
            "added_count": len(added),
            "removed_count": len(removed),
            "modified_count": len(modified),
        },
    }
