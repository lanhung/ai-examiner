import json
import sys

from ai_examiner.cli import build_corpus


def test_batch_corpus_cli_with_mock(tmp_path, monkeypatch):
    input_dir = tmp_path / "papers"
    output_dir = tmp_path / "exports"
    input_dir.mkdir()
    material = (
        "本文提出主动提问型智能系统，并把规划、分析、策略和评分拆开。"
        "实验比较多种基线，也明确讨论了泛化和证据边界。"
    ) * 20
    (input_dir / "paper.txt").write_text(material, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-examiner-build-corpus",
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--profiles",
            "mock:heuristic-v2",
            "--question-count",
            "4",
            "--limit",
            "1",
        ],
    )
    build_corpus()
    summary = json.loads((output_dir / "corpus-summary.json").read_text(encoding="utf-8"))
    assert summary["processed_count"] == 1
    assert summary["failed_count"] == 0
    assert (output_dir / "paper.golden.json").exists()
    assert len((output_dir / "paper.golden.jsonl").read_text().splitlines()) == 4
