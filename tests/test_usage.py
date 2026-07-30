# tests/test_usage.py
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


def test_main_disabled_noops(tmp_path, monkeypatch):
    usage_path = tmp_path / ".usage.json"
    monkeypatch.setattr(u, "usage_path", lambda: usage_path)
    monkeypatch.setattr(u, "load_config", lambda: {"enabled": False})
    hook = json.dumps({"tool_name": "Skill", "tool_input": {"skill": "foo"}})
    rc = u.main(stdin=io.StringIO(hook), now_iso="2026-07-14T00:00:00Z")
    assert rc == 0
    assert not usage_path.exists()          # disabled -> nothing written


def test_a_skill_hook_we_cannot_read_is_logged_as_drift(tmp_path, monkeypatch):
    # If Claude Code ever renames tool_input.skill, usage counting goes quiet and
    # every skill looks unused -- which would then feed the curator a manifest of
    # false zeros. Recording the unreadable payload is the only warning we get.
    import runlog as R
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(u, "load_config", lambda: {})
    monkeypatch.setattr(u, "log_target", lambda: log)
    hook = json.dumps({"tool_name": "Skill", "tool_input": {"name": "foo"}})
    u.main(stdin=io.StringIO(hook))
    ev = [e for e in R.read_events(log) if e["role"] == "usage"][-1]
    assert ev["outcome"] == "unreadable_skill_name"
    assert ev["tool_input_keys"] == ["name"]


def test_a_normal_skill_hook_logs_nothing(tmp_path, monkeypatch):
    # usage fires on every single Skill call; the happy path must stay silent or
    # the log becomes useless.
    import runlog as R
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(u, "load_config", lambda: {})
    monkeypatch.setattr(u, "log_target", lambda: log)
    monkeypatch.setattr(u, "usage_path", lambda: tmp_path / ".usage.json")
    hook = json.dumps({"tool_name": "Skill", "tool_input": {"skill": "foo"}})
    u.main(stdin=io.StringIO(hook))
    assert R.read_events(log) == []


def test_a_non_skill_tool_logs_nothing(tmp_path, monkeypatch):
    import runlog as R
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(u, "load_config", lambda: {})
    monkeypatch.setattr(u, "log_target", lambda: log)
    u.main(stdin=io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {}})))
    assert R.read_events(log) == []
