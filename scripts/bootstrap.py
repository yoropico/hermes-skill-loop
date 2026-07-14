# .claude/skill-loop/scripts/bootstrap.py
"""Seed ~/.claude/skill-loop.json and merge our SessionEnd/PreToolUse hook
entries into ~/.claude/settings.json — idempotently, preserving user hooks.

Run once by the BCT deployer after copying scripts (Plan 2), or by hand.
"""
from __future__ import annotations
import json, sys
from pathlib import Path


def hook_entries(scripts_dir: str) -> dict:
    learn = f'python3 "{scripts_dir}/learn.py"'
    usage = f'python3 "{scripts_dir}/usage.py"'
    return {
        "SessionEnd": [{"hooks": [{"type": "command", "command": learn, "async": True, "timeout": 300}]}],
        "PreToolUse": [{"matcher": "Skill", "hooks": [{"type": "command", "command": usage}]}],
    }


def _contains_cmd(entries: list, needle: str) -> bool:
    # Compare against the actual command values, not a json.dumps() substring:
    # dumps escapes the quotes in our commands (`"` -> `\"`), so a raw-needle
    # substring check never matches and the merge is non-idempotent.
    return any(
        needle == h.get("command")
        for e in entries
        for h in (e.get("hooks") or [])
    )


def merge_hooks(settings: dict, additions: dict) -> dict:
    settings = dict(settings)
    hooks = dict(settings.get("hooks") or {})
    for event, new_entries in additions.items():
        existing = list(hooks.get(event) or [])
        for entry in new_entries:
            cmd = entry["hooks"][0]["command"]
            if not _contains_cmd(existing, cmd):
                existing.append(entry)
        hooks[event] = existing
    settings["hooks"] = hooks
    return settings


def seed_config(path: Path, default: dict) -> bool:
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default, indent=2), encoding="utf-8")
    return True


def _load_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(settings_path=None, config_path=None, scripts_dir=None, default_config=None) -> int:
    home = Path.home() / ".claude"
    settings_path = Path(settings_path or home / "settings.json")
    config_path = Path(config_path or home / "skill-loop.json")
    scripts_dir = scripts_dir or str(home / "scripts" / "skill-loop")
    default_config = default_config or _load_json(Path(__file__).resolve().parent / "config.default.json")
    seed_config(config_path, default_config)
    merged = merge_hooks(_load_json(settings_path), hook_entries(scripts_dir))
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
