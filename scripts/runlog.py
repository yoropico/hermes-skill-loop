# .claude/skill-loop/scripts/runlog.py
"""Append-only JSONL run log for the skill loop.

Every place this loop can silently do nothing writes one line here: a swallowed
exception, an action skipped and why, a hook payload whose keys we could not read.

Why it exists: the curator ran for 16 days on an expensive model, applied exactly
nothing, and nobody could tell -- `except Exception: return []` plus a
`.curator_state` timestamp made a total no-op look healthy. Observability is the
fix for that whole class of defect, not just for the one key mismatch that caused
it. It is also the only drift detector we have for the Claude Code hook contract:
if a payload key is renamed upstream, the log fills with `no_transcript_path`
instead of the loop just going quiet.

Never raises. A log write must not be able to break the hook it instruments, so
`emit` reports failure with a return value instead of an exception, and callers
are free to ignore it.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude" / "skill-loop.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def log_path() -> Path:
    """`log_path` in ~/.claude/skill-loop.json, else ~/.claude/skill-loop.jsonl.

    One file for every role, so the learn/curate history reads chronologically in
    one place -- the question you actually ask of it is "what did the loop do
    lately", not "what did the curator do".
    """
    cfg = load_config()
    override = cfg.get("log_path")
    if isinstance(override, str) and override.strip():
        return Path(override).expanduser()
    return Path.home() / ".claude" / "skill-loop.jsonl"


def emit(role: str, event: dict, path=None, now_iso: str = None) -> bool:
    """Append one event. Returns True if it landed, False if it could not.

    `default=str` on the dump so a Path, an exception, or a datetime in the event
    degrades to its text form rather than costing us the whole line.
    """
    try:
        target = Path(path) if path is not None else log_path()
        record = {"ts": now_iso or datetime.now(timezone.utc).isoformat(), "role": role}
        record.update(event or {})
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        return False


def read_events(path=None) -> list:
    """Parse the log, skipping any line that is not valid JSON.

    A half-written line from a killed hook must not make the whole history
    unreadable -- this is a diagnostic log, so partial beats nothing.
    """
    try:
        target = Path(path) if path is not None else log_path()
        text = target.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out
