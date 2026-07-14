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


# --- firewall: never clobber a skill we did not author -----------------------

def _deployed(skills_dir, slug):
    """A BCT-deployed skill: no x-origin marker."""
    p = skills_dir / slug / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nname: %s\ndescription: shipped.\n---\n\noriginal body\n" % slug)
    return p

def test_write_skill_refuses_to_clobber_deployed_skill(tmp_path):
    # The distiller can propose a name that collides with a BCT-deployed skill.
    # Overwriting it would destroy it AND stamp it x-origin: skill-loop (curatable).
    victim = _deployed(tmp_path, "browser-preview")
    out = L.write_skill(tmp_path, {"name": "browser-preview", "description": "d", "body": "learned"})
    assert out is None
    assert victim.read_text() == "---\nname: browser-preview\ndescription: shipped.\n---\n\noriginal body\n"

def test_write_skill_may_overwrite_own_learned_skill(tmp_path):
    L.write_skill(tmp_path, {"name": "foo", "description": "v1", "body": "b1"})
    out = L.write_skill(tmp_path, {"name": "foo", "description": "v2", "body": "b2"})
    assert out is not None and "b2" in out.read_text() and "v2" in out.read_text()


# --- traceability -------------------------------------------------------------

def test_build_skill_md_records_provenance():
    md = L.build_skill_md("foo", "Use when x.", "body", session_id="abc-123", learned_on="2026-07-15")
    assert "x-learned: 2026-07-15" in md and "x-source: abc-123" in md

def test_build_skill_md_omits_provenance_when_unknown():
    md = L.build_skill_md("foo", "Use when x.", "body")
    assert "x-learned:" not in md and "x-source:" not in md


# --- update path: refine an existing skill instead of forking a stale twin ----

def test_skill_index_lists_learned_only(tmp_path):
    _deployed(tmp_path, "browser-preview")
    L.write_skill(tmp_path, {"name": "my-learned", "description": "Use when y.", "body": "b"})
    idx = L.skill_index(tmp_path)
    assert "my-learned" in idx and "Use when y." in idx
    assert "browser-preview" not in idx           # deployed skills are invisible to the loop

def test_learn_prompt_carries_the_existing_index(tmp_path):
    L.write_skill(tmp_path, {"name": "my-learned", "description": "Use when y.", "body": "b"})
    tr = tmp_path / "tr.jsonl"; tr.write_text('{"role":"user"}\n')
    seen = {}
    def fake_claude(prompt, inp):
        seen["prompt"] = prompt
        return '{"create": false}'
    L.main(stdin=io.StringIO(json.dumps({"transcript_path": str(tr)})),
           run_claude=fake_claude, skills_dir=tmp_path)
    assert "my-learned" in seen["prompt"]          # the model can SEE what it already knows

def test_main_update_path_rewrites_existing_body(tmp_path, monkeypatch):
    monkeypatch.delenv("SKILL_LOOP_INTERNAL", raising=False)
    L.write_skill(tmp_path, {"name": "deploy-x", "description": "Use when deploying.", "body": "old way"})
    tr = tmp_path / "tr.jsonl"; tr.write_text('{"role":"user"}\n')
    calls = []
    def fake_claude(prompt, inp):
        calls.append(prompt)
        if len(calls) == 1:
            return '{"update": "deploy-x"}'                       # stage 1: refine, don't fork
        assert "old way" in prompt                                # stage 2 sees the current skill
        return json.dumps({"body": "new way", "description": "Use when deploying (v2)."})
    rc = L.main(stdin=io.StringIO(json.dumps({"transcript_path": str(tr), "session_id": "sess-9"})),
                run_claude=fake_claude, skills_dir=tmp_path)
    md = (tmp_path / "deploy-x" / "SKILL.md").read_text()
    assert rc == 0 and len(calls) == 2
    assert "new way" in md and "old way" not in md
    assert "Use when deploying (v2)." in md
    assert "x-origin: skill-loop" in md and "x-source: sess-9" in md

def test_main_update_of_unknown_skill_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("SKILL_LOOP_INTERNAL", raising=False)
    tr = tmp_path / "tr.jsonl"; tr.write_text('{"role":"user"}\n')
    calls = []
    def fake_claude(prompt, inp):
        calls.append(prompt); return '{"update": "does-not-exist"}'
    rc = L.main(stdin=io.StringIO(json.dumps({"transcript_path": str(tr)})),
                run_claude=fake_claude, skills_dir=tmp_path)
    assert rc == 0 and len(calls) == 1                            # no stage 2, no write
    assert not (tmp_path / "does-not-exist").exists()

def test_main_update_of_deployed_skill_writes_nothing(tmp_path, monkeypatch):
    # "update browser-preview" must not become a back door through the firewall.
    monkeypatch.delenv("SKILL_LOOP_INTERNAL", raising=False)
    victim = _deployed(tmp_path, "browser-preview")
    tr = tmp_path / "tr.jsonl"; tr.write_text('{"role":"user"}\n')
    calls = []
    def fake_claude(prompt, inp):
        calls.append(prompt); return '{"update": "browser-preview"}'
    rc = L.main(stdin=io.StringIO(json.dumps({"transcript_path": str(tr)})),
                run_claude=fake_claude, skills_dir=tmp_path)
    assert rc == 0 and len(calls) == 1
    assert "original body" in victim.read_text()

def test_main_new_skill_records_session_id(tmp_path, monkeypatch):
    monkeypatch.delenv("SKILL_LOOP_INTERNAL", raising=False)
    tr = tmp_path / "tr.jsonl"; tr.write_text('{"role":"user"}\n')
    def fake_claude(prompt, inp):
        return json.dumps({"create": True, "name": "n", "description": "Use when n.", "body": "b"})
    L.main(stdin=io.StringIO(json.dumps({"transcript_path": str(tr), "session_id": "sess-1"})),
           run_claude=fake_claude, skills_dir=tmp_path)
    md = (tmp_path / "n" / "SKILL.md").read_text()
    assert "x-source: sess-1" in md and "x-learned: " in md
