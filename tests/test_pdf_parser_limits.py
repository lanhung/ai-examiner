from pathlib import Path

import fitz
import pytest

from ai_examiner.services.documents import parse_uploaded_document


def pdf_bytes(pages=1):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), "Synthetic PDF evidence, independent test set.")
    data = doc.tobytes()
    doc.close()
    return data


def test_pdf_subprocess_pages_limit_and_evidence(tmp_path):
    path = tmp_path / "paper.pdf"
    raw = pdf_bytes(3)
    path.write_bytes(raw)
    parsed = parse_uploaded_document(path, raw, 10000, evidence_output_dir=tmp_path / "ok")
    assert len(parsed.page_map) == 3
    assert len([e for e in parsed.evidence if e.kind == "page"]) == 3
    assert all(Path(e.storage_path).is_file() for e in parsed.evidence if e.storage_path)
    with pytest.raises(ValueError, match="2 页"):
        parse_uploaded_document(path, raw, 10000, evidence_output_dir=tmp_path / "limit", max_pdf_pages=2)


def test_pdf_timeout_is_bounded_and_sanitized(tmp_path, monkeypatch):
    import subprocess

    from ai_examiner.services import documents

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 10
        raise subprocess.TimeoutExpired("private-path", 10)

    monkeypatch.setattr(documents.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="10 秒"):
        parse_uploaded_document(tmp_path / "paper.pdf", b"x", 10000,
                                evidence_output_dir=tmp_path / "timeout", timeout_seconds=10)
