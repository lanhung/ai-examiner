"""Isolated document parser; communicates only through a private staging file."""
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .services.documents import parse_document


def main() -> int:
    path, output = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        parsed = parse_document(path, path.read_bytes(), int(sys.argv[3]), output,
                                max_pdf_pages=int(sys.argv[4]))
        result, code = asdict(parsed), 0
    except ValueError as exc:
        result, code = {"error": str(exc)}, 1
    except Exception:
        result, code = {"error": "材料解析失败，请检查文件是否损坏"}, 1
    (output / "parsed.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
