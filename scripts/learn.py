"""SessionEnd hook: distill a reusable procedure from the session transcript
into ~/.claude/skills/<slug>/SKILL.md (marked x-origin: skill-loop).

Two stages, because knowledge must be able to GROW, not only accumulate:
  1. learn.md  — sees the transcript + an index of what we already learned, and
                 answers create / update / nothing.
  2. update.md — only when stage 1 says "update <name>": sees the transcript +
                 that skill's current text, and returns the merged full body.
Without stage 2 a later, better lesson forks a stale twin instead of correcting
the original (observed: the BCT redeploy skill froze a workaround as the answer).

The `claude -p` call is injected (run_claude) so tests never hit the network.
main() never raises — a failed learn must not disrupt the user.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path

import skill_meta

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


def load_prompt(name: str = "learn.md") -> str:
    return (SCRIPT_DIR / "prompts" / name).read_text(encoding="utf-8")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40].strip("-") or "learned-skill"


def build_skill_md(name: str, description: str, body: str,
                   session_id: str | None = None, learned_on: str | None = None) -> str:
    fm = [f"name: {name}", f"description: {description}", "x-origin: skill-loop"]
    if learned_on:
        fm.append(f"x-learned: {learned_on}")
    if session_id:
        fm.append(f"x-source: {session_id}")
    return "---\n" + "\n".join(fm) + "\n---\n\n" + body.rstrip() + "\n"


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


def parse_json(out: str) -> dict | None:
    try:
        start, end = out.find("{"), out.rfind("}")
        if start == -1 or end == -1:
            return None
        data = json.loads(out[start:end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def skill_index(skills_dir: Path) -> str:
    """`- name: description` for every skill WE authored. Deployed skills are
    omitted: the loop must not be tempted to touch what it does not own."""
    lines = []
    for md in skill_meta.list_learned(Path(skills_dir)):
        fm = skill_meta.read_frontmatter(md) or {}
        lines.append(f"- {fm.get('name', md.parent.name)}: {fm.get('description', '')}".rstrip())
    return "\n".join(lines) if lines else "(none yet)"


def learned_skill_path(skills_dir: Path, name: str) -> Path | None:
    """The SKILL.md for `name`, only if it exists AND we authored it."""
    md = Path(skills_dir) / slugify(name) / "SKILL.md"
    return md if md.is_file() and skill_meta.is_learned(md) else None


def distill(transcript_text: str, prompt: str, run_claude) -> dict | None:
    data = parse_json(run_claude(prompt, transcript_text))
    if not data:
        return None
    if isinstance(data.get("update"), str) and data["update"].strip():
        return {"update": data["update"].strip()}
    if not data.get("create"):
        return None
    if not (data.get("name") and data.get("description") and data.get("body")):
        return None
    return data


def write_skill(skills_dir: Path, result: dict,
                session_id: str | None = None, learned_on: str | None = None) -> Path | None:
    """Write SKILL.md. Returns None — writing NOTHING — if the slug collides with
    a skill we did not author (a BCT-deployed one). Overwriting it would both
    destroy it and stamp it x-origin: skill-loop, handing it to the curator."""
    slug = slugify(result["name"])
    dst = Path(skills_dir) / slug / "SKILL.md"
    if dst.is_file() and not skill_meta.is_learned(dst):
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        build_skill_md(slug, result["description"], result["body"], session_id, learned_on),
        encoding="utf-8",
    )
    return dst


def refine(skills_dir: Path, name: str, transcript_text: str, run_claude) -> dict | None:
    """Stage 2: hand the model the skill's CURRENT text and let it return the
    merged body. Silently gives up unless `name` is a skill we authored."""
    md = learned_skill_path(skills_dir, name)
    if md is None:
        return None
    current = md.read_text(encoding="utf-8")
    prompt = load_prompt("update.md") + "\n\n=== CURRENT SKILL ===\n" + current
    data = parse_json(run_claude(prompt, transcript_text))
    if not data or not data.get("body"):
        return None
    fm = skill_meta.read_frontmatter(md) or {}
    return {
        "name": slugify(name),
        "description": data.get("description") or fm.get("description", ""),
        "body": data["body"],
    }


def main(stdin=None, run_claude=None, skills_dir=None, today=None) -> int:
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

        skills = Path(skills_dir or (Path.home() / ".claude" / "skills"))
        run = run_claude or default_claude
        session_id = hook.get("session_id")
        learned_on = today or time.strftime("%Y-%m-%d")

        prompt = load_prompt() + "\n\n=== SKILLS YOU HAVE ALREADY LEARNED ===\n" + skill_index(skills)
        result = distill(transcript, prompt, run)
        if not result:
            return 0
        if result.get("update"):
            result = refine(skills, result["update"], transcript, run)
            if not result:
                return 0
        write_skill(skills, result, session_id, learned_on)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
