# tests/test_migrate.py
import sys, pathlib, json, importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "migrate_off_bct",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrate-off-bct.py")
M = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(M)


def _settings_with_legacy(extra=None):
    s = {
        "hooks": {
            "SessionEnd": [
                {"hooks": [{"type": "command",
                            "command": 'python3 "/Users/someone/.claude/scripts/skill-loop/learn.py"',
                            "async": True, "timeout": 300}]},
                {"hooks": [{"type": "command",
                            "command": 'node "$HOME/.claude/hooks/agentmemory-worklog-sync.js"',
                            "async": True, "timeout": 30}]},
            ],
            "PreToolUse": [
                {"matcher": "Bash",
                 "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/guard-destructive.sh"}]},
                {"matcher": "Skill",
                 "hooks": [{"type": "command",
                            "command": 'python3 "/Users/someone/.claude/scripts/skill-loop/usage.py"'}]},
            ],
        }
    }
    if extra:
        s.update(extra)
    return s


def test_strips_only_the_legacy_entries():
    new, removed = M.strip_legacy_hooks(_settings_with_legacy())
    assert len(removed) == 2
    # The user's own hooks survive untouched -- this script must never be the
    # reason someone loses an unrelated hook.
    assert len(new["hooks"]["SessionEnd"]) == 1
    assert "agentmemory" in new["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
    assert len(new["hooks"]["PreToolUse"]) == 1
    assert new["hooks"]["PreToolUse"][0]["matcher"] == "Bash"


def test_does_not_mutate_the_input():
    original = _settings_with_legacy()
    snapshot = json.dumps(original, sort_keys=True)
    M.strip_legacy_hooks(original)
    assert json.dumps(original, sort_keys=True) == snapshot


def test_is_idempotent():
    once, removed1 = M.strip_legacy_hooks(_settings_with_legacy())
    twice, removed2 = M.strip_legacy_hooks(once)
    assert removed1 and removed2 == []
    assert twice == once


def test_drops_an_event_key_that_becomes_empty():
    s = {"hooks": {"SessionEnd": [
        {"hooks": [{"type": "command",
                    "command": 'python3 "/x/.claude/scripts/skill-loop/learn.py"'}]}]}}
    new, removed = M.strip_legacy_hooks(s)
    assert removed and "hooks" not in new          # no empty arrays left behind


def test_preserves_unrelated_top_level_settings():
    new, _ = M.strip_legacy_hooks(_settings_with_legacy({"outputStyle": "개조식 보고서"}))
    assert new["outputStyle"] == "개조식 보고서"


def test_dry_run_changes_nothing_on_disk(tmp_path, capsys):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_settings_with_legacy()), encoding="utf-8")
    payload = tmp_path / "skill-loop"; payload.mkdir()
    (payload / "learn.py").write_text("x")
    before = settings.read_text(encoding="utf-8")

    rc = M.main(["--dry-run", "--settings", str(settings), "--payload", str(payload)])
    assert rc == 0
    assert settings.read_text(encoding="utf-8") == before
    assert payload.is_dir()
    assert "Dry run" in capsys.readouterr().out


def test_real_run_strips_hooks_removes_payload_and_backs_up(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_settings_with_legacy()), encoding="utf-8")
    payload = tmp_path / "skill-loop"; payload.mkdir()
    (payload / "learn.py").write_text("x")

    rc = M.main(["--settings", str(settings), "--payload", str(payload)])
    assert rc == 0
    left = json.loads(settings.read_text(encoding="utf-8"))
    cmds = [h["command"] for entries in left["hooks"].values()
            for e in entries for h in e["hooks"]]
    assert not any("skill-loop" in c for c in cmds)
    assert not payload.exists()
    # A backup is not optional: this edits a file the user did not hand us.
    assert settings.with_suffix(".json.pre-hermes-migrate").is_file()


def test_second_real_run_is_a_no_op(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_settings_with_legacy()), encoding="utf-8")
    payload = tmp_path / "skill-loop"; payload.mkdir()
    M.main(["--settings", str(settings), "--payload", str(payload)])
    first = settings.read_text(encoding="utf-8")
    rc = M.main(["--settings", str(settings), "--payload", str(payload)])
    assert rc == 0 and settings.read_text(encoding="utf-8") == first


def test_missing_settings_file_is_not_an_error(tmp_path):
    rc = M.main(["--settings", str(tmp_path / "nope.json"),
                 "--payload", str(tmp_path / "nothing")])
    assert rc == 0
