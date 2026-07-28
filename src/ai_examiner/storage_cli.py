from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import get_settings
from .db import SessionLocal, init_db
from .services.storage_migration import (
    migrate_legacy_storage,
    reconcile_storage,
)


def run_storage_migration() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate legacy host paths to canonical tenant object storage"
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("./data/storage-migration.json"),
    )
    parser.add_argument("--delete-source", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reconcile-only", action="store_true")
    args = parser.parse_args()

    init_db()
    settings = get_settings()
    with SessionLocal() as db:
        report = (
            reconcile_storage(db, settings)
            if args.reconcile_only
            else migrate_legacy_storage(
                db,
                settings,
                checkpoint_path=args.checkpoint,
                delete_source=args.delete_source,
                dry_run=args.dry_run,
                limit=args.limit,
            )
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["summary"].get("failed") or report["summary"].get("missing"):
        raise SystemExit(1)


if __name__ == "__main__":
    run_storage_migration()
