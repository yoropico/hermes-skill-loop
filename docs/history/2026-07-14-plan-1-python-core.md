# Skill Self-Learning Loop — Plan 1: Python Core Loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the standalone, manually-installable Python core of the skill self-learning loop — distill session learnings into `~/.claude/skills/`, track usage, and curate (archive/pin, never delete) — fully unit-tested, with `claude -p` behind an injectable runner.

**Architecture:** Five small Python scripts under `.claude/skill-loop/scripts/` plus two prompt files and a default config. Pure logic (frontmatter parsing, marker filtering, usage counting, interval guards, archive-not-delete) is unit-tested; the `claude -p` subprocess is an injected function so tests never call the network. Runtime targets `~/.claude/` but every function takes explicit paths so tests use tmp dirs.

**Tech Stack:** Python 3.10+ (stdlib only — no external deps), pytest for tests. Spec: `docs/superpowers/specs/2026-07-14-skill-self-learning-loop-design.md`.

## Global Constraints

- **Stdlib only** — no pip dependencies (scripts run under whatever `python3` the user has; verified floor 3.10).
- **Marker is the firewall**: learned skills carry frontmatter `x-origin: skill-loop`. Curator touches ONLY marked skills. BCT's 7 deployed skills (unmarked) must stay invisible to the curator.
- **Never delete**: curator archives to `~/.claude/skills/_archive/<slug>/`; it never removes a skill directory.
- **Pinned bypass**: a skill with frontmatter `x-pinned: true` is never archived/consolidated.
- **`claude -p` is injectable**: every function that calls Claude takes a `run_claude` callable (default = real subprocess) so tests inject a fake.
- **Exclude `_archive/`** from every skill scan.
- All scripts live in repo at `.claude/skill-loop/`; Plan 2 (Swift) deploys them to `~/.claude/`. This plan installs manually.

---

### Task 1: `skill_meta.py` — frontmatter + learned/pinned marker helper

**Files:**
- Create: `.claude/skill-loop/scripts/skill_meta.py`
- Test: `.claude/skill-loop/tests/test_skill_meta.py`

**Interfaces:**
- Produces:
  - `MARKER_KEY = "x-origin"`, `MARKER_VAL = "skill-loop"`
  - `read_frontmatter(md_path: Path) -> dict | None` — parse the `--- … ---` block into a flat `{str: str}`; `None` if no frontmatter.
  - `is_learned(md_path: Path) -> bool` — frontmatter `x-origin == "skill-loop"`.
  - `is_pinned(md_path: Path) -> bool` — frontmatter `x-pinned` is truthy ("true"/"yes"/"1").
  - `list_learned(skills_dir: Path) -> list[Path]` — every `<skills_dir>/<slug>/SKILL.md` that `is_learned`, excluding any path under `_archive/`, sorted.

- [ ] **Step 1: Write the failing tests**

```python
# .claude/skill-loop/tests/test_skill_meta.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import skill_meta as m
from pathlib import Path

def _write(p: Path, body: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")

LEARNED = "---\nname: foo\ndescription: d\nx-origin: skill-loop\n---\n\n# Foo\n"
PLAIN   = "---\nname: bar\ndescription: d\n---\n\n# Bar\n"
NOFM    = "# Just a heading\n"

def test_read_frontmatter_parses_keys(tmp_path):
    p = tmp_path / "a" / "SKILL.md"; _write(p, LEARNED)
    fm = m.read_frontmatter(p)
    assert fm["name"] == "foo" and fm["x-origin"] == "skill-loop"

def test_read_frontmatter_none_when_absent(tmp_path):
    p = tmp_path / "b" / "SKILL.md"; _write(p, NOFM)
    assert m.read_frontmatter(p) is None

def test_is_learned_true_only_with_marker(tmp_path):
    a = tmp_path / "a" / "SKILL.md"; _write(a, LEARNED)
    b = tmp_path / "b" / "SKILL.md"; _write(b, PLAIN)
    assert m.is_learned(a) is True and m.is_learned(b) is False

def test_is_pinned(tmp_path):
    p = tmp_path / "c" / "SKILL.md"
    _write(p, "---\nname: c\nx-origin: skill-loop\nx-pinned: true\n---\n")
    assert m.is_pinned(p) is True

def test_list_learned_skips_unmarked_and_archive(tmp_path):
    skills = tmp_path / "skills"
    _write(skills / "keep" / "SKILL.md", LEARNED)
    _write(skills / "bct-native" / "SKILL.md", PLAIN)         # unmarked BCT skill
    _write(skills / "_archive" / "old" / "SKILL.md", LEARNED) # archived
    got = {p.parent.name for p in m.list_learned(skills)}
    assert got == {"keep"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest .claude/skill-loop/tests/test_skill_meta.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skill_meta'`

- [ ] **Step 3: Write the implementation**

```python
# .claude/skill-loop/scripts/skill_meta.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest .claude/skill-loop/tests/test_skill_meta.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/skill-loop/scripts/skill_meta.py .claude/skill-loop/tests/test_skill_meta.py
git commit -m "feat(skill-loop): skill_meta frontmatter + learned/pinned marker helpers"
```

---

### Task 2: `usage.py` — PreToolUse(Skill) usage tracker

**Files:**
- Create: `.claude/skill-loop/scripts/usage.py`
- Test: `.claude/skill-loop/tests/test_usage.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `skill_name_from_hook(hook: dict) -> str | None` — returns the skill name iff `hook["tool_name"] == "Skill"`; reads `hook["tool_input"]["skill"]`.
  - `bump(usage: dict, name: str, now_iso: str) -> dict` — `usage[name] = {"count": n+1, "last_used": now_iso}`.
  - `load_usage(path: Path) -> dict`, `save_usage(path: Path, usage: dict) -> None`.
  - `main(argv=None, stdin=None, now_iso=None) -> int` — reads hook JSON from stdin, bumps `~/.claude/skills/.usage.json`. Never raises (hooks must not crash the session); returns 0 always.

- [ ] **Step 1: Write the failing tests**

```python
# .claude/skill-loop/tests/test_usage.py
import sys, pathlib, io, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import usage as u

def test_skill_name_only_for_skill_tool():
    assert u.skill_name_from_hook({"tool_name": "Skill", "tool_input": {"skill": "foo"}}) == "foo"
    assert u.skill_name_from_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is None
    assert u.skill_name_from_hook({"tool_name": "Skill", "tool_input": {}}) is None

def test_bump_new_and_existing():
    us = {}
    u.bump(us, "foo", "2026-07-14T00:00:00Z")
    assert us["foo"] == {"count": 1, "last_used": "2026-07-14T00:00:00Z"}
    u.bump(us, "foo", "2026-07-14T01:00:00Z")
    assert us["foo"]["count"] == 2 and us["foo"]["last_used"] == "2026-07-14T01:00:00Z"

def test_main_writes_usage(tmp_path, monkeypatch):
    usage_path = tmp_path / ".usage.json"
    monkeypatch.setattr(u, "usage_path", lambda: usage_path)
    hook = json.dumps({"tool_name": "Skill", "tool_input": {"skill": "foo"}})
    rc = u.main(stdin=io.StringIO(hook), now_iso="2026-07-14T00:00:00Z")
    assert rc == 0
    assert json.loads(usage_path.read_text())["foo"]["count"] == 1

def test_main_ignores_non_skill(tmp_path, monkeypatch):
    usage_path = tmp_path / ".usage.json"
    monkeypatch.setattr(u, "usage_path", lambda: usage_path)
    u.main(stdin=io.StringIO('{"tool_name":"Bash","tool_input":{}}'), now_iso="x")
    assert not usage_path.exists()

def test_main_never_raises_on_garbage(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "usage_path", lambda: tmp_path / ".usage.json")
    assert u.main(stdin=io.StringIO("not json")) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest .claude/skill-loop/tests/test_usage.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'usage'`

- [ ] **Step 3: Write the implementation**

```python
# .claude/skill-loop/scripts/usage.py
"""PreToolUse(Skill) hook: count skill invocations into ~/.claude/skills/.usage.json.

Must never crash the session — main() swallows all errors and returns 0.
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path


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
        raw = (stdin or sys.stdin).read()
        hook = json.loads(raw)
        name = skill_name_from_hook(hook)
        if name:
            p = usage_path()
            us = bump(load_usage(p), name, now_iso or datetime.now(timezone.utc).isoformat())
            save_usage(p, us)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest .claude/skill-loop/tests/test_usage.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/skill-loop/scripts/usage.py .claude/skill-loop/tests/test_usage.py
git commit -m "feat(skill-loop): usage tracker PreToolUse(Skill) hook"
```

---

### Task 3: `learn.py` + `prompts/learn.md` — SessionEnd distill hook

**Files:**
- Create: `.claude/skill-loop/scripts/learn.py`
- Create: `.claude/skill-loop/prompts/learn.md`
- Test: `.claude/skill-loop/tests/test_learn.py`

**Interfaces:**
- Consumes: `skill_meta.MARKER_KEY`, `skill_meta.MARKER_VAL`.
- Produces:
  - `slugify(text: str) -> str` — lowercase, `[a-z0-9-]`, collapse dashes, ≤40 chars.
  - `build_skill_md(name: str, description: str, body: str) -> str` — SKILL.md with frontmatter `name`, `description`, `x-origin: skill-loop`.
  - `read_transcript(path: Path, retries=5, delay=0.3, sleep=time.sleep) -> str` — flush-tolerant read (retry while empty/shrinking); returns raw text (may be "").
  - `distill(transcript_text: str, prompt: str, run_claude) -> dict | None` — calls `run_claude(prompt, transcript_text)`, parses its stdout JSON `{"create": bool, "name","description","body"}`; returns the dict iff `create` is true, else `None`.
  - `write_skill(skills_dir: Path, result: dict) -> Path` — writes `<skills_dir>/<slug>/SKILL.md` via `build_skill_md`.
  - `main(stdin=None, run_claude=None, skills_dir=None) -> int` — reads SessionEnd hook JSON (`transcript_path`), distills, writes if `create`. Never raises; returns 0.

- [ ] **Step 1: Write the prompt file**

```markdown
<!-- .claude/skill-loop/prompts/learn.md -->
You are the LEARN pass of a personal skill self-learning loop. You are given the
full transcript of one Claude Code session (JSONL, one message per line).

Decide whether the session contains a **reusable procedure** worth saving as a
Claude Code skill — a concrete, repeatable how-to the user is likely to need
again (a workflow, a fix pattern, a project-specific command sequence, a
gotcha + its resolution). Ignore one-off answers, chit-chat, and anything
already obvious.

Reply with ONE JSON object and nothing else:
{"create": false}
  — if nothing reusable was learned, OR
{"create": true,
 "name": "kebab-case-name",
 "description": "One sentence starting with 'Use when …' describing the trigger.",
 "body": "Markdown body: the procedure, as steps/commands a future agent can follow."}

Be conservative: prefer {"create": false} over a low-value skill. Never include
secrets, tokens, or absolute personal paths in the body.
```

- [ ] **Step 2: Write the failing tests**

```python
# .claude/skill-loop/tests/test_learn.py
import sys, pathlib, io, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import learn as L

def test_slugify():
    assert L.slugify("Fix the Metal Shader!!") == "fix-the-metal-shader"
    assert L.slugify("a  b__c") == "a-b-c"

def test_build_skill_md_has_marker():
    md = L.build_skill_md("foo", "Use when x.", "# Foo\nbody")
    assert "x-origin: skill-loop" in md and "name: foo" in md and "# Foo" in md

def test_read_transcript_retries_until_stable(tmp_path):
    p = tmp_path / "t.jsonl"; p.write_text("")
    calls = {"n": 0}
    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] == 2:
            p.write_text('{"role":"user"}\n')   # appears on 2nd wait
    out = L.read_transcript(p, retries=5, delay=0, sleep=fake_sleep)
    assert '"role":"user"' in out

def test_distill_create_true():
    def fake_claude(prompt, inp):
        return json.dumps({"create": True, "name": "foo", "description": "Use when x.", "body": "b"})
    r = L.distill("transcript", "prompt", fake_claude)
    assert r["name"] == "foo"

def test_distill_create_false_returns_none():
    r = L.distill("t", "p", lambda p, i: '{"create": false}')
    assert r is None

def test_distill_bad_json_returns_none():
    assert L.distill("t", "p", lambda p, i: "not json") is None

def test_write_skill(tmp_path):
    path = L.write_skill(tmp_path, {"create": True, "name": "foo bar", "description": "d", "body": "x"})
    assert path == tmp_path / "foo-bar" / "SKILL.md"
    assert "x-origin: skill-loop" in path.read_text()

def test_main_end_to_end(tmp_path, monkeypatch):
    tr = tmp_path / "tr.jsonl"; tr.write_text('{"role":"user","content":"hi"}\n')
    skills = tmp_path / "skills"
    hook = json.dumps({"transcript_path": str(tr), "session_id": "s", "reason": "clear"})
    monkeypatch.setattr(L, "load_prompt", lambda: "PROMPT")
    def fake_claude(prompt, inp):
        return json.dumps({"create": True, "name": "learned-x", "description": "Use when x.", "body": "steps"})
    rc = L.main(stdin=io.StringIO(hook), run_claude=fake_claude, skills_dir=skills)
    assert rc == 0
    assert (skills / "learned-x" / "SKILL.md").exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest .claude/skill-loop/tests/test_learn.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'learn'`

- [ ] **Step 4: Write the implementation**

```python
# .claude/skill-loop/scripts/learn.py
"""SessionEnd hook: distill a reusable procedure from the session transcript
into ~/.claude/skills/<slug>/SKILL.md (marked x-origin: skill-loop).

The `claude -p` call is injected (run_claude) so tests never hit the network.
main() never raises — a failed learn must not disrupt the user.
"""
from __future__ import annotations
import json, re, subprocess, sys, time
from pathlib import Path

import skill_meta  # noqa: F401  (kept for MARKER constants / co-location)

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path.home() / ".claude" / "skill-loop.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
    model = load_config().get("model", "claude-sonnet-5")
    full = prompt + "\n\n=== TRANSCRIPT ===\n" + transcript_text
    proc = subprocess.run(
        ["claude", "-p", "--model", model],
        input=full, capture_output=True, text=True, timeout=300,
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest .claude/skill-loop/tests/test_learn.py -q`
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add .claude/skill-loop/scripts/learn.py .claude/skill-loop/prompts/learn.md .claude/skill-loop/tests/test_learn.py
git commit -m "feat(skill-loop): learn.py SessionEnd distill hook + learn prompt"
```

---

### Task 4: `curator.py` + `prompts/curate.md` — idle-triggered curator

**Files:**
- Create: `.claude/skill-loop/scripts/curator.py`
- Create: `.claude/skill-loop/prompts/curate.md`
- Test: `.claude/skill-loop/tests/test_curator.py`

**Interfaces:**
- Consumes: `skill_meta.list_learned`, `skill_meta.is_pinned`.
- Produces:
  - `should_run(state: dict, interval_hours: float, now: datetime) -> bool` — true if `now - state["last_run"] >= interval_hours` (or no last_run).
  - `load_state(path: Path) -> dict`, `save_state(path: Path, now_iso: str) -> None`.
  - `archive(skill_md: Path, archive_root: Path) -> Path` — MOVE the skill's directory under `archive_root/<slug>/`; never deletes.
  - `apply_actions(actions: list[dict], skills_dir: Path, archive_root: Path) -> list[str]` — each action `{"skill": slug, "op": "archive"|"pin"|"keep"}`; skips pinned skills on archive; returns applied ops.
  - `curate(skills_dir, archive_root, prompt, run_claude) -> list[str]` — builds a manifest of learned skills, asks `run_claude` for actions (JSON list), applies them.
  - `main(now=None, run_claude=None, skills_dir=None) -> int` — interval-guarded entry; never raises; returns 0.

- [ ] **Step 1: Write the prompt file**

```markdown
<!-- .claude/skill-loop/prompts/curate.md -->
You are the CURATOR of a personal skill collection. You are given a JSON manifest
of agent-created skills: [{ "slug", "description", "count", "last_used", "pinned" }].

Propose maintenance actions. For each skill choose exactly one op:
- "keep"    — leave as is (default; use for active, useful, distinct skills)
- "archive" — this skill is stale (unused for a long time), superseded, or a
              near-duplicate of a better one. Archiving is recoverable.
- "pin"     — this skill is clearly high-value and should never be auto-archived.

Rules: never archive a skill marked "pinned": true. Prefer "keep" when unsure —
be conservative. If two skills overlap, archive the weaker and keep the stronger.

Reply with ONE JSON array and nothing else:
[{"slug":"...","op":"keep"}, {"slug":"...","op":"archive"}, ...]
```

- [ ] **Step 2: Write the failing tests**

```python
# .claude/skill-loop/tests/test_curator.py
import sys, pathlib, json
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import curator as C

def _mk(skills, slug, pinned=False):
    p = skills / slug / "SKILL.md"; p.parent.mkdir(parents=True, exist_ok=True)
    fm = "---\nname: %s\nx-origin: skill-loop\n%s---\n\n# %s\n" % (
        slug, "x-pinned: true\n" if pinned else "", slug)
    p.write_text(fm); return p

def test_should_run_interval():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    assert C.should_run({}, 24, now) is True
    recent = {"last_run": (now - timedelta(hours=1)).isoformat()}
    assert C.should_run(recent, 24, now) is False
    old = {"last_run": (now - timedelta(hours=25)).isoformat()}
    assert C.should_run(old, 24, now) is True

def test_archive_moves_not_deletes(tmp_path):
    skills = tmp_path / "skills"; arch = skills / "_archive"
    md = _mk(skills, "old")
    dst = C.archive(md, arch)
    assert not (skills / "old").exists()          # moved out
    assert dst.exists() and "_archive" in dst.parts

def test_apply_actions_respects_pinned(tmp_path):
    skills = tmp_path / "skills"; arch = skills / "_archive"
    _mk(skills, "keepme", pinned=True)
    applied = C.apply_actions([{"skill": "keepme", "op": "archive"}], skills, arch)
    assert (skills / "keepme").exists()           # pinned bypass — NOT archived
    assert applied == []

def test_apply_actions_archives_unpinned(tmp_path):
    skills = tmp_path / "skills"; arch = skills / "_archive"
    _mk(skills, "stale")
    applied = C.apply_actions([{"skill": "stale", "op": "archive"}], skills, arch)
    assert not (skills / "stale").exists() and applied == ["archive:stale"]

def test_curate_only_marked_skills(tmp_path):
    skills = tmp_path / "skills"; arch = skills / "_archive"
    _mk(skills, "learned")
    (skills / "bct" ).mkdir(); (skills / "bct" / "SKILL.md").write_text("---\nname: bct\n---\n")
    seen = {}
    def fake_claude(prompt, manifest_json):
        seen["manifest"] = json.loads(manifest_json)
        return "[]"
    C.curate(skills, arch, "PROMPT", fake_claude)
    slugs = {e["slug"] for e in seen["manifest"]}
    assert slugs == {"learned"}                    # unmarked BCT skill excluded
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest .claude/skill-loop/tests/test_curator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'curator'`

- [ ] **Step 4: Write the implementation**

```python
# .claude/skill-loop/scripts/curator.py
"""Idle-triggered curator: reviews agent-created skills and archives/pins them.

Never deletes (archive is a move to _archive/). Touches ONLY skills marked
x-origin: skill-loop; BCT-deployed skills are invisible. Pinned skills bypass
archiving. The `claude -p` call is injected for tests. main() never raises.
"""
from __future__ import annotations
import json, shutil, subprocess, sys
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


def build_manifest(skills_dir: Path) -> list[dict]:
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


def apply_actions(actions: list[dict], skills_dir: Path, archive_root: Path) -> list[str]:
    skills_dir = Path(skills_dir)
    applied: list[str] = []
    for act in actions:
        slug, op = act.get("skill"), act.get("op")
        md = skills_dir / str(slug) / "SKILL.md"
        if not md.exists() or not skill_meta.is_learned(md):
            continue
        if op == "archive":
            if skill_meta.is_pinned(md):
                continue               # pinned bypass
            archive(md, archive_root)
            applied.append(f"archive:{slug}")
        elif op == "pin":
            _pin(md)
            applied.append(f"pin:{slug}")
    return applied


def curate(skills_dir: Path, archive_root: Path, prompt: str, run_claude) -> list[str]:
    manifest = build_manifest(skills_dir)
    if not manifest:
        return []
    try:
        out = run_claude(prompt, json.dumps(manifest))
        start, end = out.find("["), out.rfind("]")
        actions = json.loads(out[start:end + 1]) if start != -1 else []
    except Exception:
        return []
    return apply_actions(actions, skills_dir, archive_root)


def default_claude(prompt: str, manifest_json: str) -> str:
    model = load_config().get("model", "claude-sonnet-5")
    proc = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt + "\n\n=== MANIFEST ===\n" + manifest_json,
        capture_output=True, text=True, timeout=300,
    )
    return proc.stdout


def main(now=None, run_claude=None, skills_dir=None) -> int:
    try:
        now = now or datetime.now(timezone.utc)
        skills_dir = Path(skills_dir) if skills_dir else _home_skills()
        interval = float(load_config().get("curator_interval_hours", 24))
        sp = state_path() if skills_dir == _home_skills() else skills_dir / ".curator_state"
        if not should_run(load_state(sp), interval, now):
            return 0
        curate(skills_dir, skills_dir / "_archive", load_prompt(), run_claude or default_claude)
        save_state(sp, now.isoformat())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest .claude/skill-loop/tests/test_curator.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add .claude/skill-loop/scripts/curator.py .claude/skill-loop/prompts/curate.md .claude/skill-loop/tests/test_curator.py
git commit -m "feat(skill-loop): curator.py idle review (archive/pin, never delete, marked-only)"
```

---

### Task 5: `bootstrap.py` + `config.default.json` — settings.json hook merge + config seed

**Files:**
- Create: `.claude/skill-loop/scripts/bootstrap.py`
- Create: `.claude/skill-loop/config.default.json`
- Test: `.claude/skill-loop/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `hook_entries(scripts_dir: str) -> dict` — the `{"SessionEnd": [...], "PreToolUse": [...]}` blocks to merge (commands referencing `learn.py` / `usage.py` under `scripts_dir`).
  - `merge_hooks(settings: dict, additions: dict) -> dict` — idempotent: for each event, append our entry only if no existing entry contains our command string; preserves all user entries.
  - `seed_config(path: Path, default: dict) -> bool` — writes `default` iff `path` absent; returns True if written.
  - `main(settings_path=None, config_path=None, scripts_dir=None, default_config=None) -> int`.

- [ ] **Step 1: Write the default config**

```json
{
  "enabled": true,
  "model": "claude-sonnet-5",
  "idle_threshold_minutes": 10,
  "curator_interval_hours": 24
}
```
(save as `.claude/skill-loop/config.default.json`)

- [ ] **Step 2: Write the failing tests**

```python
# .claude/skill-loop/tests/test_bootstrap.py
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap as b

def test_merge_adds_when_absent():
    s = b.merge_hooks({}, b.hook_entries("/S"))
    cmds = json.dumps(s)
    assert "learn.py" in cmds and "usage.py" in cmds
    assert "SessionEnd" in s["hooks"] and "PreToolUse" in s["hooks"]

def test_merge_idempotent():
    add = b.hook_entries("/S")
    s1 = b.merge_hooks({}, add)
    s2 = b.merge_hooks(s1, add)
    assert s1 == s2                       # no duplicate entries

def test_merge_preserves_user_hooks():
    user = {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "my.sh"}]}]}}
    s = b.merge_hooks(user, b.hook_entries("/S"))
    dumped = json.dumps(s)
    assert "my.sh" in dumped and "learn.py" in dumped

def test_seed_config_only_when_absent(tmp_path):
    p = tmp_path / "skill-loop.json"
    assert b.seed_config(p, {"enabled": True}) is True
    assert b.seed_config(p, {"enabled": False}) is False   # already exists
    assert json.loads(p.read_text())["enabled"] is True    # unchanged
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest .claude/skill-loop/tests/test_bootstrap.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'bootstrap'`

- [ ] **Step 4: Write the implementation**

```python
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
    return needle in json.dumps(entries)


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
    default_config = default_config or _load_json(Path(__file__).resolve().parents[1] / "config.default.json")
    seed_config(config_path, default_config)
    merged = merge_hooks(_load_json(settings_path), hook_entries(scripts_dir))
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest .claude/skill-loop/tests/test_bootstrap.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add .claude/skill-loop/scripts/bootstrap.py .claude/skill-loop/config.default.json .claude/skill-loop/tests/test_bootstrap.py
git commit -m "feat(skill-loop): bootstrap settings.json hook merge + config seed"
```

---

### Task 6: Manual install + full-suite verification + README

**Files:**
- Create: `.claude/skill-loop/README.md`

**Interfaces:** none (documentation + verification).

- [ ] **Step 1: Run the full pytest suite**

Run: `python3 -m pytest .claude/skill-loop/tests/ -q`
Expected: PASS (27 passed) — all of Tasks 1–5.

- [ ] **Step 2: Write the README (manual install for Plan-1-only use)**

```markdown
<!-- .claude/skill-loop/README.md -->
# Skill self-learning loop (Python core)

Personal loop that distills reusable procedures from Claude Code sessions into
`~/.claude/skills/`, tracks usage, and curates (archive/pin, never delete).
Learned skills are marked `x-origin: skill-loop`; BCT-deployed skills are never
touched. See `docs/superpowers/specs/2026-07-14-skill-self-learning-loop-design.md`.

## Manual install (Plan 2 automates this via BCT)

```bash
mkdir -p ~/.claude/scripts/skill-loop
cp -R .claude/skill-loop/scripts/* ~/.claude/scripts/skill-loop/
cp -R .claude/skill-loop/prompts   ~/.claude/scripts/skill-loop/prompts
python3 ~/.claude/scripts/skill-loop/bootstrap.py   # merges hooks, seeds config
```

## Curator (until Plan 2's BCT idle trigger exists)

```bash
python3 ~/.claude/scripts/skill-loop/curator.py     # interval-guarded (24h)
```

## Config: `~/.claude/skill-loop.json`
`enabled`, `model`, `idle_threshold_minutes`, `curator_interval_hours`.
```

- [ ] **Step 3: Live smoke (manual, real Claude)**

1. `python3 ~/.claude/scripts/skill-loop/bootstrap.py` → confirm `~/.claude/settings.json` gained a `SessionEnd`(learn) and `PreToolUse`(Skill→usage) entry, and `~/.claude/skill-loop.json` exists.
2. Run a short throwaway `claude` session that performs a small repeatable procedure, then exit → after a moment, confirm a new `~/.claude/skills/<slug>/SKILL.md` with `x-origin: skill-loop`.
3. Invoke any skill in a session → confirm `~/.claude/skills/.usage.json` bumped.
4. `python3 curator.py` → runs once; second immediate run is a no-op (interval guard).
5. Confirm a BCT-deployed skill (e.g. `terminal-control`, unmarked) is untouched by the curator.

- [ ] **Step 4: Commit**

```bash
git add .claude/skill-loop/README.md
git commit -m "docs(skill-loop): README + manual install; Plan 1 core complete"
```

---

## Self-Review

**Spec coverage:**
- ① learn hook → Task 3 ✅ · ② usage tracker → Task 2 ✅ · ③ curator → Task 4 ✅ · ⑥ marker/safety → Task 1 (+ enforced in Tasks 3/4) ✅ · externalized prompts → Tasks 3/4 ✅ · config → Task 5 ✅ · settings.json hook merge → Task 5 ✅.
- **Deferred to Plan 2** (BCT integration, explicitly out of scope here): ④ `SkillLoopDeploy.swift` deploy, StatusbarBridge global-idle watcher, `SkillLoopSyncTests`. Plan 1 covers manual install (Task 6) so it is working software on its own.

**Placeholder scan:** none — every step has real code/commands and expected output.

**Type consistency:** `skill_meta.is_learned/is_pinned/list_learned/read_frontmatter` used identically across Tasks 3/4; `run_claude(prompt, payload) -> str` signature identical in learn.distill and curator.curate; `archive(skill_md, archive_root)` and `apply_actions` names consistent; marker string `x-origin: skill-loop` identical everywhere.

## Next: Plan 2 (BCT integration)

After Plan 1 lands (suite green, manual smoke ok), write `docs/superpowers/plans/2026-07-14-skill-loop-2-bct-integration.md`:
`SkillLoopDeploy.swift` (embed + deploy scripts/prompts/config mirroring the 7 SkillDeploy, run bootstrap.py, wire into `BCTMain.main()`), StatusbarBridge global-idle predicate + curator spawn (via `Process()`), and `SkillLoopSyncTests` (embedded == repo source). Hook contracts already verified.

## Implementation notes (applied during execution — supersede the task bodies above)

- **Prompts + config live under `scripts/`**, not directly under `.claude/skill-loop/`.
  Final layout: `scripts/prompts/{learn,curate}.md`, `scripts/config.default.json`.
  Reason: `learn.py`/`curator.py` resolve `load_prompt()` at `SCRIPT_DIR/prompts/`,
  and `bootstrap.py` resolves the default config at `Path(__file__).parent/config.default.json`.
  Keeping everything under `scripts/` makes repo-run == deployed-run (Plan 2's
  `cp -R scripts/* ~/.claude/scripts/skill-loop/` copies prompts + config too).
- **`bootstrap.py` idempotency fix**: `_contains_cmd` compares actual `command`
  values, not a `json.dumps()` substring (dumps escapes the quotes in our
  commands, so the substring guard never matched → non-idempotent merge).
- **`bootstrap.py` config path**: `Path(__file__).resolve().parent / "config.default.json"`
  (was `parents[1]`, which pointed outside the deployed scripts dir).
- **Test runner**: system `python3` is 3.9 without pytest — run the suite via
  `uv run --with pytest --python 3.11 python -m pytest …` (uv is installed).
- **Result**: full suite 27 passed. Commits `1327d78` (Task 1) + `0ed707b`,
  `10f3352`, `c2344a6`, `bda8ef8` (Tasks 2–5).
