# scripts/usage.py
"""PreToolUse(Skill) hook: count skill invocations into ~/.claude/skills/.usage.json.

Must never crash the session — main() swallows all errors and returns 0.

Fires on every single Skill call, so the happy path logs NOTHING; only a payload
we cannot read is recorded. That one case matters out of proportion: if upstream
renames `tool_input.skill`, counting stops, every skill starts looking unused, and
the curator is then fed a manifest of false zeros it would act on.
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

import runlog

CONFIG_PATH = Path.home() / ".claude" / "skill-loop.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def log_target():
    """Indirection so tests can redirect the log without reaching into runlog."""
    return runlog.log_path()


def usage_path() -> Path:
    return Path.home() / ".claude" / "skills" / ".usage.json"


def skill_name_from_hook(hook: dict) -> str | None:
    if hook.get("tool_name") != "Skill":
        return None
    name = (hook.get("tool_input") or {}).get("skill")
    return name if isinstance(name, str) and name else None


def bump(usage: dict, name: str, now_iso: str) -> dict:
    entry = usage.get(name) or {"count": 0, "last_used": None}
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last_used"] = now_iso
    usage[name] = entry
    return usage


def load_usage(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_usage(path: Path, usage: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(usage, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def main(argv=None, stdin=None, now_iso=None) -> int:
    try:
        if load_config().get("enabled") is False:
            return 0
        raw = (stdin or sys.stdin).read()
        hook = json.loads(raw)
        name = skill_name_from_hook(hook)
        if name:
            p = usage_path()
            us = bump(load_usage(p), name, now_iso or datetime.now(timezone.utc).isoformat())
            save_usage(p, us)
        elif hook.get("tool_name") == "Skill":
            # It IS a Skill call and we still could not name it -> the payload
            # shape moved. Record the keys we got; that is the whole warning.
            runlog.emit("usage",
                        {"outcome": "unreadable_skill_name",
                         "tool_input_keys": sorted((hook.get("tool_input") or {}).keys())},
                        path=log_target(), now_iso=now_iso)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
