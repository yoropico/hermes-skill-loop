# tests/test_doctor.py
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import doctor as D


def _by_name(checks):
    return {c["name"]: c for c in checks}


# --- individual checks -------------------------------------------------------

def test_python_check_fails_below_3_9():
    assert D.check_python((3, 8, 10))["status"] == D.FAIL
    assert D.check_python((3, 9, 6))["status"] == D.OK
    assert D.check_python((3, 13, 0))["status"] == D.OK


def test_claude_cli_check_reports_the_resolved_path():
    ok = D.check_claude_cli(which=lambda n: "/usr/local/bin/claude")
    assert ok["status"] == D.OK and "/usr/local/bin/claude" in ok["detail"]
    # Without the CLI the loop cannot distill or curate at all -- that is fatal,
    # not a warning, and it is exactly what a silent `error` outcome looks like.
    assert D.check_claude_cli(which=lambda n: None)["status"] == D.FAIL


def test_config_check_resolves_both_models():
    c = D.check_config({"model": "m-shared", "curator_model": "m-cur"})
    assert c["status"] == D.OK
    assert "learn=m-shared" in c["detail"] and "curator=m-cur" in c["detail"]


def test_config_check_flags_the_kill_switch():
    c = D.check_config({"enabled": False})
    assert c["status"] == D.WARN and "enabled: false" in c["detail"]


def test_config_check_warns_on_a_stale_model_generation():
    # A retired model id makes `claude -p` fail, which the loop can only record --
    # it cannot fix. Naming the risk before it bites is the whole point of doctor.
    c = D.check_config({"curator_model": "claude-opus-4-8"})
    assert c["status"] == D.WARN
    assert "claude-opus-4-8" in c["detail"]


def test_log_writable_check(tmp_path):
    assert D.check_log_writable(tmp_path / "sub" / "log.jsonl")["status"] == D.OK
    blocker = tmp_path / "file"; blocker.write_text("x")
    assert D.check_log_writable(blocker / "log.jsonl")["status"] == D.FAIL


def test_hooks_firing_check_uses_the_log_as_evidence():
    # We cannot introspect Claude Code's active hook table, but a learn or usage
    # event IS proof the hooks fired. No events at all means "not wired yet".
    assert D.check_hooks_firing([])["status"] == D.WARN
    assert D.check_hooks_firing([{"role": "curator", "outcome": "dry_run"}])["status"] == D.WARN
    ok = D.check_hooks_firing([{"role": "learn", "outcome": "nothing", "ts": "2026-07-30T00:00:00+00:00"}])
    assert ok["status"] == D.OK


def test_last_run_check_reports_the_outcome():
    evs = [{"role": "curator", "outcome": "applied", "ts": "2026-07-30T00:00:00+00:00",
            "proposed": 3, "kept": 1, "applied": ["archive:a"], "skipped": [{"slug": "b"}]}]
    c = D.check_last_curator_run(evs)
    assert c["status"] == D.OK and "applied" in c["detail"]


def test_last_run_check_surfaces_an_error_outcome():
    evs = [{"role": "curator", "outcome": "error", "error": "RuntimeError: model is gone",
            "ts": "2026-07-30T00:00:00+00:00"}]
    c = D.check_last_curator_run(evs)
    assert c["status"] == D.FAIL and "model is gone" in c["detail"]


def test_last_run_check_flags_unparseable():
    evs = [{"role": "curator", "outcome": "unparseable", "raw_head": "I refuse",
            "ts": "2026-07-30T00:00:00+00:00"}]
    assert D.check_last_curator_run(evs)["status"] == D.FAIL


def test_reconciliation_check_catches_dropped_actions():
    # THE check that would have caught the 2026-07-14..30 no-op on day one:
    # 10 proposed, 0 kept, 0 applied, 0 skipped -> ten actions went nowhere.
    evs = [{"role": "curator", "outcome": "applied", "ts": "2026-07-30T00:00:00+00:00",
            "proposed": 10, "kept": 0, "applied": [], "skipped": []}]
    c = D.check_reconciliation(evs)
    assert c["status"] == D.FAIL
    assert "10" in c["detail"]


def test_reconciliation_check_passes_when_the_numbers_add_up():
    evs = [{"role": "curator", "outcome": "applied", "ts": "2026-07-30T00:00:00+00:00",
            "proposed": 4, "kept": 2, "applied": ["pin:a"], "skipped": [{"slug": "b"}]}]
    assert D.check_reconciliation(evs)["status"] == D.OK


def test_reconciliation_check_is_silent_with_no_run_to_judge():
    assert D.check_reconciliation([])["status"] == D.WARN


# --- skills inventory --------------------------------------------------------

def _mk(skills, slug, desc="Use when x.", learned="2026-06-01", body="b", learned_marker=True):
    p = skills / slug / "SKILL.md"; p.parent.mkdir(parents=True, exist_ok=True)
    fm = ["name: %s" % slug, "description: %s" % desc]
    if learned_marker:
        fm.append("x-origin: skill-loop")
    fm.append("x-learned: %s" % learned)
    p.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + body + "\n", encoding="utf-8")
    return p


def test_skills_check_counts_and_prices_the_listing(tmp_path):
    skills = tmp_path / "skills"
    _mk(skills, "used-one")
    _mk(skills, "never-used-one")
    _mk(skills, "not-ours", learned_marker=False)
    usage = {"used-one": {"count": 4}}
    c = D.check_skills(skills, usage)
    assert c["status"] == D.OK
    assert "learned=2" in c["detail"]          # the unmarked one is invisible
    assert "never-used=1" in c["detail"]
    assert "tok" in c["detail"]                # listing cost is reported


def test_skills_check_warns_when_never_used_dominates(tmp_path):
    skills = tmp_path / "skills"
    for i in range(5):
        _mk(skills, "cold-%d" % i)
    _mk(skills, "warm")
    c = D.check_skills(skills, {"warm": {"count": 3}})
    # 5 of 6 unused past the age floor is the signature of a curator that is not
    # actually curating -- warn rather than pass it off as normal.
    assert c["status"] == D.WARN


def test_truncated_slug_check_reports_mid_word_cuts(tmp_path):
    skills = tmp_path / "skills"
    _mk(skills, "a" * 40)                       # exactly at the cap -> suspect
    _mk(skills, "short-name")
    c = D.check_truncated_slugs(skills)
    assert c["status"] == D.WARN and "1" in c["detail"]


def test_missing_description_check_is_a_real_failure(tmp_path):
    # A skill with no description can never be matched: it is dead weight that
    # still costs a listing line.
    skills = tmp_path / "skills"
    _mk(skills, "fine")
    _mk(skills, "blank", desc="")
    c = D.check_descriptions(skills)
    assert c["status"] == D.FAIL and "blank" in c["detail"]


# --- assembly ----------------------------------------------------------------

def test_run_checks_returns_every_check_once(tmp_path):
    skills = tmp_path / "skills"; _mk(skills, "one")
    checks = D.run_checks(skills_dir=skills, usage={}, config={}, events=[],
                          log_path=tmp_path / "log.jsonl",
                          version_info=(3, 12, 0), which=lambda n: "/bin/claude")
    names = [c["name"] for c in checks]
    assert len(names) == len(set(names))
    for expected in ("python", "claude-cli", "config", "log", "hooks", "skills"):
        assert expected in names


def test_main_exits_nonzero_when_a_check_fails(tmp_path, monkeypatch, capsys):
    skills = tmp_path / "skills"; _mk(skills, "one")
    monkeypatch.setattr(D, "_gather", lambda: dict(
        skills_dir=skills, usage={}, config={}, events=[],
        log_path=tmp_path / "log.jsonl", version_info=(3, 12, 0),
        which=lambda n: None))            # no claude CLI -> FAIL
    rc = D.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out and "claude-cli" in out


def test_main_exits_zero_when_everything_is_fine(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    _mk(skills, "one"); _mk(skills, "two")
    monkeypatch.setattr(D, "_gather", lambda: dict(
        skills_dir=skills, usage={"one": {"count": 2}, "two": {"count": 1}},
        config={"model": "claude-sonnet-5"},
        events=[{"role": "learn", "outcome": "created", "ts": "2026-07-30T00:00:00+00:00"}],
        log_path=tmp_path / "log.jsonl", version_info=(3, 12, 0),
        which=lambda n: "/bin/claude"))
    assert D.main([]) == 0


def test_render_marks_each_status_visibly():
    text = D.render([
        {"name": "a", "status": D.OK, "detail": "fine"},
        {"name": "b", "status": D.WARN, "detail": "hmm"},
        {"name": "c", "status": D.FAIL, "detail": "broken"},
    ])
    assert "OK" in text and "WARN" in text and "FAIL" in text
    assert "broken" in text
