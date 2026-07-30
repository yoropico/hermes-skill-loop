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
main() never raises — a failed learn must not disrupt the user. But "never raises"
used to mean "never explains", so every exit now records its outcome in the run
log (see runlog.py). That log is also the loop's only detector for Claude Code
changing the SessionEnd payload: if `transcript_path` is ever renamed upstream,
learn goes quiet, and the only way to notice is a run of `no_transcript_path`
lines rather than nothing at all.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path

import runlog
import skill_meta

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path.home() / ".claude" / "skill-loop.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def log_target():
    """Indirection so tests can redirect the log without reaching into runlog."""
    return runlog.log_path()


def learn_model() -> str:
    # `learn_model` (per-role) > `model` (shared) > default. learn runs on every
    # session end, so it can stay cheaper than the rarer curator.
    c = load_config()
    return c.get("learn_model") or c.get("model") or "claude-sonnet-5"


def load_prompt(name: str = "learn.md") -> str:
    return (SCRIPT_DIR / "prompts" / name).read_text(encoding="utf-8")


SLUG_CAP = 40


def _dashed(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def slugify(text: str) -> str:
    """Slug for a skill name, truncated at a WORD boundary.

    A hard cut at 40 produced names like `chromium-extension-indexeddb-offline-rea`
    (14 of them, live). The slug is a matching signal, so a severed final word is
    worse than no final word — drop the whole unfinished token instead. Falls back
    to a hard cut when there is no boundary to cut at (one very long word).
    """
    s = _dashed(text)
    if len(s) <= SLUG_CAP:
        return s or "learned-skill"
    cut = s[:SLUG_CAP]
    if "-" in cut:
        cut = cut[:cut.rfind("-")]
    return cut.strip("-") or s[:SLUG_CAP].strip("-") or "learned-skill"


def legacy_slug(text: str) -> str:
    """The pre-2026-07-30 hard cut. Kept ONLY so skills already written under it
    stay resolvable — never used to name anything new."""
    s = _dashed(text)
    return s[:SLUG_CAP].strip("-") or "learned-skill"


def slug_candidates(text: str) -> list:
    """Every directory name a given skill name may live under, best first."""
    out = [slugify(text)]
    legacy = legacy_slug(text)
    if legacy != out[0]:
        out.append(legacy)
    return out


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
    """The SKILL.md for `name`, only if it exists AND we authored it.

    Checks the legacy hard-cut slug as well as the current one. Without that, the
    word-boundary change would quietly stop resolving the 14 skills already on
    disk under the old name — and every later lesson about them would fork a stale
    twin instead of correcting the original, which is the precise failure the
    two-stage learn exists to prevent.
    """
    for slug in slug_candidates(name):
        md = Path(skills_dir) / slug / "SKILL.md"
        if md.is_file() and skill_meta.is_learned(md):
            return md
    return None


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
    a skill we did not author (a deployed one). Overwriting it would both destroy
    it and stamp it x-origin: skill-loop, handing it to the curator.

    An existing skill of ours wins over a fresh slug, including one written under
    the legacy hard-cut name — otherwise the boundary-truncation change would fork
    a twin beside every one of them."""
    existing = learned_skill_path(skills_dir, result["name"])
    if existing is not None:
        slug, dst = existing.parent.name, existing
    else:
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


def _log(event: dict) -> None:
    runlog.emit("learn", event, path=log_target())


def main(stdin=None, run_claude=None, skills_dir=None, today=None) -> int:
    session_id = None
    started = time.time()
    try:
        # Reentrancy guard: we are inside our own distill `claude -p` — its
        # SessionEnd fires this hook again; do nothing (else infinite recursion).
        # Deliberately unlogged: this fires for every nested call we make, and the
        # noise would bury the events worth reading.
        if os.environ.get("SKILL_LOOP_INTERNAL"):
            return 0
        if load_config().get("enabled") is False:
            return 0                       # kill-switch: silence is the point
        hook = json.loads((stdin or sys.stdin).read())
        session_id = hook.get("session_id")
        tpath = hook.get("transcript_path")
        if not tpath:
            # Contract signal, not a shrug: either the payload really lacks the
            # key or upstream renamed it. Record the keys we DID get so the
            # difference is diagnosable from the log alone.
            _log({"outcome": "skipped", "reason": "no_transcript_path",
                  "session_id": session_id, "hook_keys": sorted(hook.keys())})
            return 0
        transcript = read_transcript(Path(tpath))
        if not transcript.strip():
            _log({"outcome": "skipped", "reason": "empty_transcript",
                  "session_id": session_id, "transcript_path": str(tpath)})
            return 0

        skills = Path(skills_dir or (Path.home() / ".claude" / "skills"))
        run = run_claude or default_claude
        learned_on = today or time.strftime("%Y-%m-%d")

        prompt = load_prompt() + "\n\n=== SKILLS YOU HAVE ALREADY LEARNED ===\n" + skill_index(skills)
        result = distill(transcript, prompt, run)
        if not result:
            _log({"outcome": "nothing", "session_id": session_id,
                  "model": learn_model(),
                  "duration_ms": int((time.time() - started) * 1000)})
            return 0
        updating = bool(result.get("update"))
        target = result.get("update") if updating else None
        if updating:
            result = refine(skills, target, transcript, run)
            if not result:
                _log({"outcome": "skipped", "reason": "refine_refused",
                      "session_id": session_id, "target": target,
                      "model": learn_model()})
                return 0
        written = write_skill(skills, result, session_id, learned_on)
        if written is None:
            # The slug collides with a skill we did not author; writing would both
            # destroy it and hand it to the curator. Worth knowing it happened.
            _log({"outcome": "refused", "reason": "slug_owned_by_another_skill",
                  "session_id": session_id, "slug": slugify(result["name"])})
            return 0
        _log({"outcome": "updated" if updating else "created",
              "session_id": session_id, "slug": slugify(result["name"]),
              "model": learn_model(),
              "duration_ms": int((time.time() - started) * 1000)})
    except Exception as e:
        _log({"outcome": "error", "session_id": session_id,
              "error": "%s: %s" % (type(e).__name__, e)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
