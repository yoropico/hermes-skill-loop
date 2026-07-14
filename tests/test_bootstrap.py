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
