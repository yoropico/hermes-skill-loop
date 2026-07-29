# .claude/skill-loop/scripts/curator.py
"""Idle-triggered curator: reviews agent-created skills and archives/pins them.

Never deletes (archive is a move to _archive/). Touches ONLY skills marked
x-origin: skill-loop; BCT-deployed skills are invisible. Pinned skills bypass
archiving. The `claude -p` call is injected for tests. main() never raises.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

import skill_meta

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path.home() / ".claude" / "skill-loop.json"


def _home_skills() -> Path:
    return Path.home() / ".claude" / "skills"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def curator_model() -> str:
    # `curator_model` (per-role) > `model` (shared) > default. curation is rare
    # (interval-guarded) so it can afford a stronger model than learn.
    c = load_config()
    return c.get("curator_model") or c.get("model") or "claude-sonnet-5"


def load_prompt() -> str:
    return (SCRIPT_DIR / "prompts" / "curate.md").read_text(encoding="utf-8")


def state_path() -> Path:
    return _home_skills() / ".curator_state"


def load_state(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path: Path, now_iso: str) -> None:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_run": now_iso}), encoding="utf-8")


def should_run(state: dict, interval_hours: float, now: datetime) -> bool:
    last = state.get("last_run")
    if not last:
        return True
    try:
        prev = datetime.fromisoformat(last)
    except ValueError:
        return True
    return (now - prev).total_seconds() >= interval_hours * 3600


def _usage(skills_dir: Path) -> dict:
    try:
        return json.loads((skills_dir / ".usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def skill_age_days(skill_md: Path, now: datetime) -> int | None:
    """Age of a learned skill in whole days. Prefers the `x-learned` frontmatter
    (authoritative), falling back to the file's mtime for skills distilled before
    provenance stamping existed. Without an age signal `count == 0` is ambiguous
    ("stale" vs "just born"), so the curator must never archive on count alone."""
    fm = skill_meta.read_frontmatter(skill_md) or {}
    learned = fm.get("x-learned")
    born: datetime | None = None
    if learned:
        try:
            born = datetime.strptime(learned.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            born = None
    if born is None:
        try:
            born = datetime.fromtimestamp(Path(skill_md).stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None
    return max(0, (now - born).days)


def build_manifest(skills_dir: Path, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    usage = _usage(skills_dir)
    out = []
    for md in skill_meta.list_learned(skills_dir):
        slug = md.parent.name
        fm = skill_meta.read_frontmatter(md) or {}
        u = usage.get(slug, {})
        out.append({
            "slug": slug,
            "description": fm.get("description", ""),
            "count": u.get("count", 0),
            "last_used": u.get("last_used"),
            "age_days": skill_age_days(md, now),
            "pinned": skill_meta.is_pinned(md),
        })
    return out


def archive(skill_md: Path, archive_root: Path) -> Path:
    src_dir = Path(skill_md).parent
    dst_dir = Path(archive_root) / src_dir.name
    dst_dir.parent.mkdir(parents=True, exist_ok=True)
    if dst_dir.exists():
        shutil.rmtree(dst_dir)          # replace an older archived copy of same slug
    shutil.move(str(src_dir), str(dst_dir))
    return dst_dir / "SKILL.md"


def _pin(skill_md: Path) -> None:
    text = Path(skill_md).read_text(encoding="utf-8")
    if "x-pinned:" in text:
        return
    text = text.replace("x-origin: skill-loop\n", "x-origin: skill-loop\nx-pinned: true\n", 1)
    Path(skill_md).write_text(text, encoding="utf-8")


def apply_actions(actions: list[dict], skills_dir: Path, archive_root: Path,
                  min_age_days: int = 0, now: datetime | None = None) -> list[str]:
    skills_dir = Path(skills_dir)
    now = now or datetime.now(timezone.utc)
    applied: list[str] = []
    for act in actions:
        # `slug` is what prompts/curate.md tells the model to emit (it mirrors the
        # manifest field name); `skill` is accepted as a synonym so a model that
        # echoes the older key still lands. Reading only one of the two silently
        # drops every action -- the curator then stamps .curator_state and looks
        # healthy while doing nothing (live no-op, 2026-07-14..30).
        slug, op = act.get("slug") or act.get("skill"), act.get("op")
        md = skills_dir / str(slug) / "SKILL.md"
        if not md.exists() or not skill_meta.is_learned(md):
            continue
        if op == "archive":
            if skill_meta.is_pinned(md):
                continue               # pinned bypass
            age = skill_age_days(md, now)
            if age is not None and age < min_age_days:
                continue               # age floor: too young to be called "stale"
            archive(md, archive_root)
            applied.append(f"archive:{slug}")
        elif op == "pin":
            _pin(md)
            applied.append(f"pin:{slug}")
    return applied


def curate(skills_dir: Path, archive_root: Path, prompt: str, run_claude,
           min_age_days: int = 0, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    manifest = build_manifest(skills_dir, now)
    if not manifest:
        return []
    try:
        out = run_claude(prompt, json.dumps(manifest))
        start, end = out.find("["), out.rfind("]")
        actions = json.loads(out[start:end + 1]) if start != -1 else []
    except Exception:
        return []
    return apply_actions(actions, skills_dir, archive_root, min_age_days, now)


def default_claude(prompt: str, manifest_json: str) -> str:
    model = curator_model()
    proc = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt + "\n\n=== MANIFEST ===\n" + manifest_json,
        capture_output=True, text=True, timeout=300,
        # Mark this nested session so its SessionEnd (learn.py) hook no-ops.
        env={**os.environ, "SKILL_LOOP_INTERNAL": "1"},
    )
    return proc.stdout


def main(now=None, run_claude=None, skills_dir=None) -> int:
    try:
        if load_config().get("enabled") is False:
            return 0
        now = now or datetime.now(timezone.utc)
        skills_dir = Path(skills_dir) if skills_dir else _home_skills()
        cfg = load_config()
        interval = float(cfg.get("curator_interval_hours", 24))
        min_age = int(cfg.get("curator_min_age_days", 7))
        sp = state_path() if skills_dir == _home_skills() else skills_dir / ".curator_state"
        if not should_run(load_state(sp), interval, now):
            return 0
        curate(skills_dir, skills_dir / "_archive", load_prompt(),
               run_claude or default_claude, min_age, now)
        save_state(sp, now.isoformat())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
