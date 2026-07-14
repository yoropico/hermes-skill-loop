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


def test_default_claude_sets_reentrancy_env(monkeypatch):
    # The `claude -p` we spawn must carry a sentinel so its own SessionEnd no-ops.
    captured = {}
    class R:  # noqa: E701
        stdout = "{}"
    monkeypatch.setattr(L.subprocess, "run", lambda cmd, **kw: (captured.update(kw), R())[1])
    monkeypatch.setattr(L, "load_config", lambda: {"model": "m"})
    L.default_claude("PROMPT", "transcript")
    assert captured["env"].get("SKILL_LOOP_INTERNAL") == "1"


def test_main_reentrancy_guard_when_internal_env(tmp_path, monkeypatch):
    # Inside our own distill `claude -p`, SessionEnd fires again — must NOT re-distill.
    monkeypatch.setenv("SKILL_LOOP_INTERNAL", "1")
    tr = tmp_path / "tr.jsonl"; tr.write_text('{"role":"user","content":"hi"}\n')
    called = {"n": 0}
    def boom(prompt, inp):
        called["n"] += 1
        return json.dumps({"create": True, "name": "x", "description": "d", "body": "b"})
    hook = json.dumps({"transcript_path": str(tr)})
    rc = L.main(stdin=io.StringIO(hook), run_claude=boom, skills_dir=tmp_path / "skills")
    assert rc == 0
    assert called["n"] == 0                       # never distilled
    assert not (tmp_path / "skills").exists()      # never wrote


def test_main_disabled_noops(tmp_path, monkeypatch):
    monkeypatch.delenv("SKILL_LOOP_INTERNAL", raising=False)
    monkeypatch.setattr(L, "load_config", lambda: {"enabled": False})
    tr = tmp_path / "tr.jsonl"; tr.write_text('{"role":"user"}\n')
    called = {"n": 0}
    def boom(prompt, inp):
        called["n"] += 1; return "{}"
    rc = L.main(stdin=io.StringIO(json.dumps({"transcript_path": str(tr)})),
                run_claude=boom, skills_dir=tmp_path / "skills")
    assert rc == 0 and called["n"] == 0


def test_learn_model_precedence(monkeypatch):
    monkeypatch.setattr(L, "load_config", lambda: {"learn_model": "A", "model": "B"})
    assert L.learn_model() == "A"                       # per-role override wins
    monkeypatch.setattr(L, "load_config", lambda: {"model": "B"})
    assert L.learn_model() == "B"                       # falls back to shared `model`
    monkeypatch.setattr(L, "load_config", lambda: {})
    assert L.learn_model() == "claude-sonnet-5"          # default


def test_default_claude_uses_learn_model(monkeypatch):
    seen = {}
    class R:  # noqa: E701
        stdout = "{}"
    def fake_run(cmd, **kw):
        seen["cmd"] = cmd; return R()
    monkeypatch.setattr(L.subprocess, "run", fake_run)
    monkeypatch.setattr(L, "load_config", lambda: {"learn_model": "learn-x"})
    L.default_claude("P", "T")
    assert "--model" in seen["cmd"] and "learn-x" in seen["cmd"]
