from __future__ import annotations

import hashlib

from ai_examiner.recovery_evidence import _psycopg_url, file_manifest


def test_file_manifest_is_relative_deterministic_and_content_bound(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "object.bin").write_bytes(b"object")

    manifest = file_manifest(tmp_path)

    assert manifest == {
        "nested/object.bin": hashlib.sha256(b"object").hexdigest(),
    }


def test_psycopg_url_removes_sqlalchemy_driver_suffix_and_can_switch_database():
    result = _psycopg_url(
        "postgresql+psycopg://user:password@127.0.0.1:5433/source",
        database="restored",
    )

    assert result == "postgresql://user:password@127.0.0.1:5433/restored"
