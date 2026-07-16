import os
import sqlite3
import stat
import tarfile
from types import SimpleNamespace

from ai_examiner import ops


def test_create_backup_uses_consistent_sqlite_snapshot(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    upload_dir = data_dir / "uploads"
    backup_dir = data_dir / "backups"
    upload_dir.mkdir(parents=True)
    (upload_dir / "sample.txt").write_text("sample", encoding="utf-8")

    database_path = data_dir / "ai_examiner.db"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
    connection.execute("INSERT INTO sample VALUES ('ready')")
    connection.commit()

    settings = SimpleNamespace(
        database_url=f"sqlite:///{database_path.as_posix()}",
        backup_dir=backup_dir,
        upload_dir=upload_dir,
    )
    monkeypatch.setattr(ops, "get_settings", lambda: settings)

    destination = ops.create_backup(backup_dir / "snapshot.tar.gz")
    connection.close()

    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    with tarfile.open(destination, "r:gz") as archive:
        names = archive.getnames()
        assert "uploads/sample.txt" in names
        assert "ai_examiner.db" in names
        assert "ai_examiner.db-wal" not in names
        assert "ai_examiner.db-shm" not in names
        archive.extract("ai_examiner.db", path=tmp_path / "restore", filter="data")

    restored = sqlite3.connect(tmp_path / "restore" / "ai_examiner.db")
    try:
        assert restored.execute("SELECT value FROM sample").fetchone() == ("ready",)
    finally:
        restored.close()
