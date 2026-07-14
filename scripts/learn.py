"""SessionEnd hook: distill a reusable procedure from the session transcript
into ~/.claude/skills/<slug>/SKILL.md (marked x-origin: skill-loop).

The `claude -p` call is injected (run_claude) so tests never hit the network.
main() never raises — a failed learn must not disrupt the user.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path

import skill_meta  # noqa: F401  (kept for MARKER constants / co-location)

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path.home() / ".claude" / "skill-loop.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def learn_model() -> str:
    # `learn_model` (per-role) > `model` (shared) > default. learn runs on every
    # session end, so it can stay cheaper than the rarer curator.
    c = load_config()
    return c.get("learn_model") or c.get("model") or "claude-sonnet-5"


def load_prompt() -> str:
    return (SCRIPT_DIR / "prompts" / "learn.md").read_text(encoding="utf-8")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40].strip("-") or "learned-skill"


def build_skill_md(name: str, description: str, body: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "x-origin: skill-loop\n"
        "---\n\n"
        f"{body.rstrip()}\n"
    )


def read_transcript(path: Path, retries: int = 5, delay: float = 0.3, sleep=time.sleep) -> str:
    path = Path(path)
    prev = -1
    for _ in range(max(retries, 1)):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        size = len(text)
        if size > 0 and size == prev:      # stable and non-empty
            return text
        prev = size
        sleep(delay)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def default_claude(prompt: str, transcript_text: str) -> str:
    model = learn_model()
    full = prompt + "\n\n=== TRANSCRIPT ===\n" + transcript_text
    proc = subprocess.run(
        ["claude", "-p", "--model", model],
        input=full, capture_output=True, text=True, timeout=300,
        # Mark this nested session so its own SessionEnd hook no-ops (no recursion).
        env={**os.environ, "SKILL_LOOP_INTERNAL": "1"},
    )
    return proc.stdout


def distill(transcript_text: str, prompt: str, run_claude) -> dict | None:
    try:
        out = run_claude(prompt, transcript_text)
        start, end = out.find("{"), out.rfind("}")
        if start == -1 or end == -1:
            return None
        data = json.loads(out[start:end + 1])
    except Exception:
        return None
    if not data.get("create"):
        return None
    if not (data.get("name") and data.get("description") and data.get("body")):
        return None
    return data


def write_skill(skills_dir: Path, result: dict) -> Path:
    slug = slugify(result["name"])
    dst = Path(skills_dir) / slug / "SKILL.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(build_skill_md(slug, result["description"], result["body"]), encoding="utf-8")
    return dst


def main(stdin=None, run_claude=None, skills_dir=None) -> int:
    try:
        # Reentrancy guard: we are inside our own distill `claude -p` — its
        # SessionEnd fires this hook again; do nothing (else infinite recursion).
        if os.environ.get("SKILL_LOOP_INTERNAL"):
            return 0
        if load_config().get("enabled") is False:
            return 0
        hook = json.loads((stdin or sys.stdin).read())
        tpath = hook.get("transcript_path")
        if not tpath:
            return 0
        transcript = read_transcript(Path(tpath))
        if not transcript.strip():
            return 0
        result = distill(transcript, load_prompt(), run_claude or default_claude)
        if result:
            write_skill(skills_dir or (Path.home() / ".claude" / "skills"), result)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
