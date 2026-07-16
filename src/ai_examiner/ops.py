from __future__ import annotations

import argparse
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from .config import get_settings


def create_backup(destination: Path | None = None) -> Path:
    settings = get_settings()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = destination or settings.backup_dir / f"ai-examiner-{stamp}.tar.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    data_root = settings.upload_dir.parent

    database_url = make_url(settings.database_url)
    database_path = (
        Path(database_url.database).resolve()
        if database_url.drivername.startswith("sqlite")
        and database_url.database
        and database_url.database != ":memory:"
        else None
    )

    with tempfile.TemporaryDirectory(prefix="ai-examiner-backup-") as temp_dir:
        snapshot_path: Path | None = None
        if database_path and database_path.exists():
            snapshot_path = Path(temp_dir) / database_path.name
            with (
                closing(sqlite3.connect(database_path, timeout=30)) as source,
                closing(sqlite3.connect(snapshot_path)) as snapshot,
            ):
                source.backup(snapshot)

        with tarfile.open(destination, "w:gz") as archive:
            excluded = {settings.backup_dir.resolve()}
            if database_path:
                excluded.update(
                    {
                        database_path,
                        Path(f"{database_path}-wal"),
                        Path(f"{database_path}-shm"),
                    }
                )
            for child in data_root.iterdir():
                if child.resolve() in excluded:
                    continue
                archive.add(child, arcname=child.name)
            if snapshot_path:
                try:
                    database_arcname = database_path.relative_to(data_root.resolve())
                except ValueError:
                    database_arcname = Path(database_path.name)
                archive.add(snapshot_path, arcname=database_arcname.as_posix())

    destination.chmod(0o600)
    return destination


def backup_cli() -> None:
    parser = argparse.ArgumentParser(description="Create a local AI Examiner data backup")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    print(create_backup(args.output))


if __name__ == "__main__":
    backup_cli()
