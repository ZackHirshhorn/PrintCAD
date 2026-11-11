"""Bundled example scripts."""
from __future__ import annotations

from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent / "examples"


def _meta(source: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in source.splitlines():
        if not line.startswith("# "):
            break
        key, _, value = line[2:].partition(":")
        meta[key.strip()] = value.strip()
    return meta


def list_examples() -> list[dict[str, str]]:
    out = []
    for path in sorted(EXAMPLES_DIR.glob("*.py")):
        source = path.read_text()
        meta = _meta(source)
        out.append(
            {
                "name": path.stem,
                "title": meta.get("title", path.stem),
                "description": meta.get("description", ""),
                "script": source,
            }
        )
    return out


def get_example(name: str) -> dict[str, str]:
    for ex in list_examples():
        if ex["name"] == name:
            return ex
    raise KeyError(f"Unknown example '{name}'")
