from __future__ import annotations

from importlib.resources import files

from ...template_engine.parser import parse_template_document


def load_builtin_template(filename: str) -> dict:
    if "/" in filename or "\\" in filename or not filename.endswith((".yaml", ".json")):
        raise ValueError("Invalid built-in template filename")
    resource = files(__package__).joinpath(filename)
    return parse_template_document(resource.read_bytes())


__all__ = ["load_builtin_template"]
