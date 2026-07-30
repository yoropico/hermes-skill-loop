# tests/test_runlog.py
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import runlog as R


def test_emit_writes_one_json_line_with_ts_and_role(tmp_path):
    log = tmp_path / "skill-loop.jsonl"
    assert R.emit("curator", {"applied": ["archive:x"]}, path=log, now_iso="2026-07-30T00:00:00+00:00")
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    ev = json.loads(lines[0])
    assert ev["ts"] == "2026-07-30T00:00:00+00:00"
    assert ev["role"] == "curator"
    assert ev["applied"] == ["archive:x"]


def test_emit_appends_never_truncates(tmp_path):
    log = tmp_path / "skill-loop.jsonl"
    R.emit("learn", {"n": 1}, path=log)
    R.emit("curator", {"n": 2}, path=log)
    evs = R.read_events(log)
    assert [e["n"] for e in evs] == [1, 2]
    assert [e["role"] for e in evs] == ["learn", "curator"]


def test_emit_creates_missing_parent_dirs(tmp_path):
    log = tmp_path / "deep" / "nested" / "skill-loop.jsonl"
    assert R.emit("curator", {"ok": True}, path=log)
    assert log.is_file()


def test_emit_never_raises_and_reports_failure(tmp_path):
    # A log write must not be able to break the hook it instruments: the whole
    # point of this module is to make silent paths visible, so it may never
    # become a new silent path of its own -- or a loud one.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    assert R.emit("curator", {"ok": True}, path=blocker / "log.jsonl") is False


def test_emit_survives_unserializable_values(tmp_path):
    log = tmp_path / "skill-loop.jsonl"
    assert R.emit("curator", {"path": pathlib.Path("/tmp/x"), "err": ValueError("boom")}, path=log)
    ev = R.read_events(log)[0]
    assert "/tmp/x" in ev["path"] and "boom" in ev["err"]


def test_read_events_tolerates_a_corrupt_line(tmp_path):
    log = tmp_path / "skill-loop.jsonl"
    R.emit("curator", {"n": 1}, path=log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    R.emit("curator", {"n": 2}, path=log)
    assert [e["n"] for e in R.read_events(log)] == [1, 2]


def test_log_path_honours_config_override(monkeypatch, tmp_path, unpatched_log_path):
    monkeypatch.setattr(R, "load_config", lambda: {"log_path": str(tmp_path / "custom.jsonl")})
    assert unpatched_log_path() == tmp_path / "custom.jsonl"


def test_log_path_defaults_under_dot_claude(monkeypatch, tmp_path, unpatched_log_path):
    monkeypatch.setattr(R, "load_config", lambda: {})
    monkeypatch.setattr(R.Path, "home", staticmethod(lambda: tmp_path))
    assert unpatched_log_path() == tmp_path / ".claude" / "skill-loop.jsonl"


def test_the_suite_can_never_write_to_the_real_log(isolated_run_log, tmp_path):
    # Pins the conftest guard itself. Without it, any test calling main() forges
    # events into ~/.claude/skill-loop.jsonl -- the one file you would trust to
    # tell you what the loop really did (found live on 2026-07-30: 10 fake events).
    import curator, learn, usage
    real = pathlib.Path.home() / ".claude" / "skill-loop.jsonl"
    for resolved in (R.log_path(), curator.log_target(), learn.log_target(), usage.log_target()):
        assert resolved == isolated_run_log
        assert resolved != real
