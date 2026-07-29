# .claude/skill-loop/scripts/curator.py
"""Idle-triggered curator: reviews agent-created skills and archives/pins them.

Never deletes (archive is a move to _archive/). Touches ONLY skills marked
x-origin: skill-loop; BCT-deployed skills are invisible. Pinned skills bypass
archiving. The `claude -p` call is injected for tests. main() never raises.

Every run leaves one line in the run log (see runlog.py): what the model proposed,
what was applied, what was skipped and why, what failed. That is not decoration --
a bare `except Exception: return []` plus a `.curator_state` timestamp let this
script apply literally nothing for 16 days while looking perfectly healthy.
`--dry-run` exists for the same reason: you can ask what it WOULD do without
letting it.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

import runlog
import skill_meta

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path.home() / ".claude" / "skill-loop.json"

# Why an action did not happen. Recorded per action, so a quiet run is readable
# instead of merely quiet.
SKIP_NOT_LEARNED = "not_a_learned_skill"   # unknown slug, or a skill we don't own
SKIP_PINNED = "pinned"
SKIP_TOO_YOUNG = "too_young"
SKIP_UNKNOWN_OP = "unknown_op"


def _home_skills() -> Path:
    return Path.home() / ".claude" / "skills"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def log_target():
    """Indirection so tests can redirect the log without reaching into runlog."""
    return runlog.log_path()


def curator_model() -> str:
    # `curator_model` (per-role) > `model` (shared) > default. curation is rare
    # (interval-guarded) so it can afford a stronger model than learn.
    c = load_config()
    return c.get("curator_model") or c.get("model") or "claude-sonnet-5"


def load_prompt() -> str:
    return (SCRIPT_DIR / "prompts" / "curate.md").read_text(encoding="utf-8")


def parse_args(argv=None) -> dict:
    argv = list(argv or [])
    return {"dry_run": "--dry-run" in argv or "-n" in argv}


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


def plan_actions(actions: list, skills_dir, min_age_days: int = 0,
                 now: datetime | None = None):
    """Decide what each proposed action would do WITHOUT touching the filesystem.

    Returns (planned, skipped). Splitting the judgement from the execution is what
    makes --dry-run honest: the preview runs the exact same decision the real run
    does, rather than a parallel approximation free to drift out of agreement.
    """
    skills_dir = Path(skills_dir)
    now = now or datetime.now(timezone.utc)
    planned, skipped = [], []
    for act in actions:
        if not isinstance(act, dict):
            continue
        # `slug` is what prompts/curate.md tells the model to emit (it mirrors the
        # manifest field name); `skill` is accepted as a synonym so a model that
        # echoes the older key still lands. Reading only one of the two silently
        # drops every action -- the curator then stamps .curator_state and looks
        # healthy while doing nothing (live no-op, 2026-07-14..30).
        slug, op = act.get("slug") or act.get("skill"), act.get("op")
        if op == "keep":
            continue                                    # counted by the caller
        md = skills_dir / str(slug) / "SKILL.md"
        if not md.exists() or not skill_meta.is_learned(md):
            skipped.append({"slug": slug, "op": op, "reason": SKIP_NOT_LEARNED})
            continue
        if op == "archive":
            if skill_meta.is_pinned(md):
                skipped.append({"slug": slug, "op": op, "reason": SKIP_PINNED})
                continue
            age = skill_age_days(md, now)
            if age is not None and age < min_age_days:
                skipped.append({"slug": slug, "op": op, "reason": SKIP_TOO_YOUNG,
                                "age_days": age, "floor": min_age_days})
                continue
            planned.append({"slug": slug, "op": op, "md": md})
        elif op == "pin":
            planned.append({"slug": slug, "op": op, "md": md})
        else:
            skipped.append({"slug": slug, "op": op, "reason": SKIP_UNKNOWN_OP})
    return planned, skipped


def _execute(planned: list, archive_root):
    """Carry out planned actions. Returns (applied_labels, failures)."""
    applied, failed = [], []
    for p in planned:
        try:
            if p["op"] == "archive":
                archive(p["md"], archive_root)
            else:
                _pin(p["md"])
            applied.append("%s:%s" % (p["op"], p["slug"]))
        except Exception as e:
            failed.append({"slug": p["slug"], "op": p["op"],
                           "error": "%s: %s" % (type(e).__name__, e)})
    return applied, failed


def apply_actions(actions: list, skills_dir, archive_root,
                  min_age_days: int = 0, now: datetime | None = None) -> list:
    planned, _skipped = plan_actions(actions, skills_dir, min_age_days, now)
    applied, _failed = _execute(planned, archive_root)
    return applied


def _parse_actions(out: str):
    """The JSON array in the model's reply, or None if there is not one."""
    try:
        start, end = out.find("["), out.rfind("]")
        if start == -1 or end == -1 or end < start:
            return None
        data = json.loads(out[start:end + 1])
    except Exception:
        return None
    return data if isinstance(data, list) else None


def curate(skills_dir, archive_root, prompt: str, run_claude,
           min_age_days: int = 0, now: datetime | None = None,
           dry_run: bool = False) -> dict:
    """Run one curation. Returns the record of what happened -- which is exactly
    what gets logged, so the log can never disagree with the behaviour."""
    now = now or datetime.now(timezone.utc)
    manifest = build_manifest(skills_dir, now)
    rec = {"outcome": "empty", "dry_run": bool(dry_run),
           "manifest_count": len(manifest), "proposed": 0, "kept": 0,
           "applied": [], "would_apply": [], "skipped": [], "failed": []}
    if not manifest:
        return rec

    started = time.time()
    try:
        out = run_claude(prompt, json.dumps(manifest))
    except Exception as e:
        # A dead model id, a missing `claude` binary, a timeout -- all of these
        # used to present as "the curator thought about it and chose nothing".
        rec["outcome"] = "error"
        rec["error"] = "%s: %s" % (type(e).__name__, e)
        rec["duration_ms"] = int((time.time() - started) * 1000)
        return rec
    rec["duration_ms"] = int((time.time() - started) * 1000)

    actions = _parse_actions(out)
    if actions is None:
        rec["outcome"] = "unparseable"
        rec["raw_head"] = (out or "")[:200]
        return rec

    planned, skipped = plan_actions(actions, skills_dir, min_age_days, now)
    rec["proposed"] = len(actions)
    rec["kept"] = sum(1 for a in actions if isinstance(a, dict) and a.get("op") == "keep")
    rec["skipped"] = skipped
    labels = ["%s:%s" % (p["op"], p["slug"]) for p in planned]
    if dry_run:
        rec["outcome"] = "dry_run"
        rec["would_apply"] = labels
        return rec
    rec["applied"], rec["failed"] = _execute(planned, archive_root)
    rec["outcome"] = "applied"
    return rec


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


def main(now=None, run_claude=None, skills_dir=None, dry_run: bool = False) -> int:
    rec = None
    now = now or datetime.now(timezone.utc)
    try:
        cfg = load_config()
        if cfg.get("enabled") is False:
            return 0
        skills_dir = Path(skills_dir) if skills_dir else _home_skills()
        interval = float(cfg.get("curator_interval_hours", 24))
        min_age = int(cfg.get("curator_min_age_days", 7))
        sp = state_path() if skills_dir == _home_skills() else skills_dir / ".curator_state"
        # A preview is not a run: it ignores the interval guard (ask any time) and
        # never stamps the clock (so it cannot consume the day's real run).
        if not dry_run and not should_run(load_state(sp), interval, now):
            runlog.emit("curator",
                        {"outcome": "skipped", "reason": "interval",
                         "interval_hours": interval,
                         "last_run": load_state(sp).get("last_run")},
                        path=log_target(), now_iso=now.isoformat())
            return 0
        rec = curate(skills_dir, skills_dir / "_archive", load_prompt(),
                     run_claude or default_claude, min_age, now, dry_run=dry_run)
        rec["model"] = curator_model()
        if not dry_run:
            save_state(sp, now.isoformat())
    except Exception as e:
        runlog.emit("curator",
                    {"outcome": "error", "error": "%s: %s" % (type(e).__name__, e)},
                    path=log_target(), now_iso=now.isoformat())
        return 0
    finally:
        if rec is not None:
            runlog.emit("curator", rec, path=log_target(), now_iso=now.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run=parse_args(sys.argv[1:])["dry_run"]))
