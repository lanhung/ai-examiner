from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BUILTIN_CORPUS_DIR = Path(__file__).parent / "corpus"


@dataclass(frozen=True)
class Material:
    id: str
    domain: str
    language: str
    title: str
    text: str


def parse_material(path: Path) -> Material:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        _, header, body = raw.split("---", 2)
        for line in header.strip().splitlines():
            key, _, value = line.partition(":")
            if key.strip():
                meta[key.strip()] = value.strip()
    return Material(
        id=meta.get("id") or path.stem,
        domain=meta.get("domain") or "general",
        language=meta.get("language") or "zh-CN",
        title=meta.get("title") or path.stem,
        text=body.strip(),
    )


def load_corpus(
    directories: list[Path] | None = None,
    *,
    include_builtin: bool = True,
    only: set[str] | None = None,
) -> list[Material]:
    sources = ([BUILTIN_CORPUS_DIR] if include_builtin else []) + list(directories or [])
    materials: dict[str, Material] = {}
    for directory in sources:
        for path in sorted(Path(directory).glob("*.md")):
            material = parse_material(path)
            if only and material.id not in only and material.domain not in only:
                continue
            materials[material.id] = material
    return list(materials.values())
