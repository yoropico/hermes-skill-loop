"""Frontmatter + marker helpers for the skill self-learning loop.

The `x-origin: skill-loop` marker is the firewall: only skills carrying it are
agent-created and eligible for curation. BCT-deployed skills (unmarked) are
invisible to every function here that filters by `is_learned`.
"""
from __future__ import annotations
from pathlib import Path

MARKER_KEY = "x-origin"
MARKER_VAL = "skill-loop"


def read_frontmatter(md_path: Path) -> dict | None:
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    fm: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip()
    return fm or None


def is_learned(md_path: Path) -> bool:
    fm = read_frontmatter(md_path)
    return bool(fm) and fm.get(MARKER_KEY) == MARKER_VAL


def is_pinned(md_path: Path) -> bool:
    fm = read_frontmatter(md_path)
    return bool(fm) and str(fm.get("x-pinned", "")).lower() in ("true", "yes", "1")


def list_learned(skills_dir: Path) -> list[Path]:
    skills_dir = Path(skills_dir)
    out: list[Path] = []
    if not skills_dir.is_dir():
        return out
    for md in sorted(skills_dir.glob("*/SKILL.md")):
        if "_archive" in md.parts:
            continue
        if is_learned(md):
            out.append(md)
    return out
