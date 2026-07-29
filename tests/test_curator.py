# .claude/skill-loop/tests/test_curator.py
import sys, pathlib, json, re
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import curator as C

def _mk(skills, slug, pinned=False, learned_on=None):
    p = skills / slug / "SKILL.md"; p.parent.mkdir(parents=True, exist_ok=True)
    fm = "---\nname: %s\nx-origin: skill-loop\n%s%s---\n\n# %s\n" % (
        slug,
        "x-pinned: true\n" if pinned else "",
        "x-learned: %s\n" % learned_on if learned_on else "",
        slug)
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


def test_default_claude_sets_reentrancy_env(monkeypatch):
    # curator's `claude -p` also triggers SessionEnd->learn; sentinel breaks that recursion.
    captured = {}
    class R:  # noqa: E701
        stdout = "[]"
    monkeypatch.setattr(C.subprocess, "run", lambda cmd, **kw: (captured.update(kw), R())[1])
    monkeypatch.setattr(C, "load_config", lambda: {"model": "m"})
    C.default_claude("PROMPT", "[]")
    assert captured["env"].get("SKILL_LOOP_INTERNAL") == "1"


def test_main_disabled_noops(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "load_config", lambda: {"enabled": False})
    _mk(tmp_path / "skills", "learned")
    called = {"n": 0}
    def boom(prompt, manifest_json):
        called["n"] += 1; return "[]"
    rc = C.main(now=datetime(2026, 7, 14, tzinfo=timezone.utc),
                run_claude=boom, skills_dir=tmp_path / "skills")
    assert rc == 0 and called["n"] == 0


def test_curator_model_precedence(monkeypatch):
    monkeypatch.setattr(C, "load_config", lambda: {"curator_model": "X", "model": "Y"})
    assert C.curator_model() == "X"                     # per-role override wins
    monkeypatch.setattr(C, "load_config", lambda: {"model": "Y"})
    assert C.curator_model() == "Y"                     # falls back to shared `model`
    monkeypatch.setattr(C, "load_config", lambda: {})
    assert C.curator_model() == "claude-sonnet-5"        # default


def test_default_claude_uses_curator_model(monkeypatch):
    seen = {}
    class R:  # noqa: E701
        stdout = "[]"
    def fake_run(cmd, **kw):
        seen["cmd"] = cmd; return R()
    monkeypatch.setattr(C.subprocess, "run", fake_run)
    monkeypatch.setattr(C, "load_config", lambda: {"curator_model": "cur-x"})
    C.default_claude("P", "[]")
    assert "--model" in seen["cmd"] and "cur-x" in seen["cmd"]


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def test_manifest_exposes_age_days_from_x_learned(tmp_path):
    # x-learned is the authoritative age signal; 30 days before NOW.
    skills = tmp_path / "skills"
    _mk(skills, "old", learned_on="2026-06-15")
    m = {e["slug"]: e for e in C.build_manifest(skills, now=NOW)}
    assert m["old"]["age_days"] == 30


def test_manifest_age_falls_back_to_mtime_when_no_x_learned(tmp_path):
    # Skills learned before x-learned existed must still get an age (file mtime),
    # never None — otherwise the archive floor can't protect/judge them.
    skills = tmp_path / "skills"
    _mk(skills, "legacy")                       # freshly written now -> ~0 days
    m = {e["slug"]: e for e in C.build_manifest(skills, now=NOW)}
    assert isinstance(m["legacy"]["age_days"], int)
    assert m["legacy"]["age_days"] >= 0


def test_apply_actions_refuses_to_archive_young_skill(tmp_path):
    # A brand-new (age 0) zero-count skill must survive an archive proposal:
    # count=0 means "stale" only once it has had a fair chance (age >= floor).
    skills = tmp_path / "skills"; arch = skills / "_archive"
    _mk(skills, "fresh", learned_on="2026-07-15")   # age 0 at NOW
    applied = C.apply_actions([{"skill": "fresh", "op": "archive"}], skills, arch,
                              min_age_days=7, now=NOW)
    assert (skills / "fresh").exists()          # protected by the age floor
    assert applied == []


def test_apply_actions_archives_old_skill_past_floor(tmp_path):
    skills = tmp_path / "skills"; arch = skills / "_archive"
    _mk(skills, "aged", learned_on="2026-06-01")    # >floor days old at NOW
    applied = C.apply_actions([{"skill": "aged", "op": "archive"}], skills, arch,
                              min_age_days=7, now=NOW)
    assert not (skills / "aged").exists() and applied == ["archive:aged"]


def test_apply_actions_pin_ignores_age_floor(tmp_path):
    # The age floor guards archives only; pinning a young skill is always allowed.
    skills = tmp_path / "skills"; arch = skills / "_archive"
    _mk(skills, "fresh", learned_on="2026-07-15")
    applied = C.apply_actions([{"skill": "fresh", "op": "pin"}], skills, arch,
                              min_age_days=7, now=NOW)
    assert applied == ["pin:fresh"]
    assert "x-pinned: true" in (skills / "fresh" / "SKILL.md").read_text()


def test_main_threads_configured_age_floor(tmp_path, monkeypatch):
    # End-to-end: main() must read curator_min_age_days and let it veto an archive
    # the model proposes for a young skill.
    #
    # DIFFERENTIAL, on purpose: the same proposal must go THROUGH when the floor is
    # 0. A survive-only assertion passes even when the action never reaches the
    # applier at all -- which is exactly how this test stayed green while the
    # applier read a key the prompt never emits (curator no-op, 2026-07-14..30).
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    def model(prompt, manifest_json):
        return '[{"slug":"fresh","op":"archive"}]'

    floored = tmp_path / "floored"
    _mk(floored, "fresh", learned_on="2026-07-15")
    monkeypatch.setattr(C, "load_config",
                        lambda: {"curator_min_age_days": 7, "curator_interval_hours": 0})
    assert C.main(now=NOW, run_claude=model, skills_dir=floored) == 0
    assert (floored / "fresh").exists()         # age floor vetoed the archive

    unfloored = tmp_path / "unfloored"
    _mk(unfloored, "fresh", learned_on="2026-07-15")
    monkeypatch.setattr(C, "load_config",
                        lambda: {"curator_min_age_days": 0, "curator_interval_hours": 0})
    assert C.main(now=NOW, run_claude=model, skills_dir=unfloored) == 0
    assert not (unfloored / "fresh").exists()   # no floor -> the action really applies


def test_apply_actions_accepts_the_slug_key_the_prompt_emits(tmp_path):
    # curate.md instructs the model to reply with {"slug": ..., "op": ...}. The
    # applier must read that key; otherwise every proposed action is silently
    # dropped and the curator is a no-op that still stamps .curator_state.
    skills = tmp_path / "skills"; arch = skills / "_archive"
    _mk(skills, "stale", learned_on="2026-06-01")
    applied = C.apply_actions([{"slug": "stale", "op": "archive"}], skills, arch,
                              min_age_days=7, now=NOW)
    assert not (skills / "stale").exists()
    assert applied == ["archive:stale"]


def test_prompt_reply_key_is_honoured_by_the_applier(tmp_path):
    # Contract guard against prompt<->code drift: whatever identifier key
    # prompts/curate.md tells the model to emit MUST be a key apply_actions
    # reads. Editing the prompt's reply shape without touching the applier is
    # the defect this pins down.
    prompt = (pathlib.Path(C.__file__).resolve().parent / "prompts" / "curate.md").read_text()
    keys = set(re.findall(r'\{"(\w+)"\s*:\s*"\.\.\."\s*,\s*"op"', prompt))
    assert keys, "curate.md no longer documents a reply shape this test can read"
    for i, key in enumerate(sorted(keys)):
        skills = tmp_path / ("k%d" % i); arch = skills / "_archive"
        _mk(skills, "aged", learned_on="2026-06-01")
        applied = C.apply_actions([{key: "aged", "op": "archive"}], skills, arch,
                                  min_age_days=7, now=NOW)
        assert applied == ["archive:aged"], "applier ignores prompt key %r" % key


# --- observability -----------------------------------------------------------
# The no-op survived 16 days because every failure path returned quietly. These
# pin the reverse: whatever the curator does or declines to do leaves a record.

import runlog as R  # noqa: E402


def _log(tmp_path):
    return tmp_path / "log.jsonl"


def test_run_logs_proposed_and_applied(tmp_path, monkeypatch):
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "aged", learned_on="2026-06-01")
    monkeypatch.setattr(C, "load_config", lambda: {"curator_interval_hours": 0})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    monkeypatch.setattr(C, "log_target", lambda: log)
    C.main(now=NOW, run_claude=lambda p, m: '[{"slug":"aged","op":"archive"}]',
           skills_dir=skills)
    ev = [e for e in R.read_events(log) if e["role"] == "curator"][-1]
    assert ev["applied"] == ["archive:aged"]
    assert ev["proposed"] == 1
    assert ev["manifest_count"] == 1
    assert ev["outcome"] == "applied"


def test_run_logs_the_model_error_instead_of_swallowing_it(tmp_path, monkeypatch):
    # `except Exception: return []` is exactly how a dead model id or a missing
    # `claude` binary would present as "the curator decided to do nothing".
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "aged", learned_on="2026-06-01")
    monkeypatch.setattr(C, "load_config", lambda: {"curator_interval_hours": 0})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    monkeypatch.setattr(C, "log_target", lambda: log)
    def boom(prompt, manifest_json):
        raise RuntimeError("model is gone")
    C.main(now=NOW, run_claude=boom, skills_dir=skills)
    ev = [e for e in R.read_events(log) if e["role"] == "curator"][-1]
    assert ev["outcome"] == "error"
    assert "model is gone" in ev["error"]


def test_run_logs_unparseable_model_output(tmp_path, monkeypatch):
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "aged", learned_on="2026-06-01")
    monkeypatch.setattr(C, "load_config", lambda: {"curator_interval_hours": 0})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    monkeypatch.setattr(C, "log_target", lambda: log)
    C.main(now=NOW, run_claude=lambda p, m: "I refuse to answer in JSON.",
           skills_dir=skills)
    ev = [e for e in R.read_events(log) if e["role"] == "curator"][-1]
    assert ev["outcome"] == "unparseable"


def test_skipped_actions_are_logged_with_a_reason(tmp_path, monkeypatch):
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "pinned", pinned=True, learned_on="2026-06-01")
    _mk(skills, "young", learned_on="2026-07-15")
    monkeypatch.setattr(C, "load_config",
                        lambda: {"curator_interval_hours": 0, "curator_min_age_days": 7})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    monkeypatch.setattr(C, "log_target", lambda: log)
    proposal = '[{"slug":"pinned","op":"archive"},{"slug":"young","op":"archive"},' \
               '{"slug":"ghost","op":"archive"}]'
    C.main(now=NOW, run_claude=lambda p, m: proposal, skills_dir=skills)
    ev = [e for e in R.read_events(log) if e["role"] == "curator"][-1]
    reasons = {s["slug"]: s["reason"] for s in ev["skipped"]}
    assert reasons == {"pinned": "pinned", "young": "too_young", "ghost": "not_a_learned_skill"}
    assert ev["applied"] == []


def test_interval_guard_skip_is_logged(tmp_path, monkeypatch):
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "aged", learned_on="2026-06-01")
    (skills / ".curator_state").write_text(json.dumps({"last_run": NOW.isoformat()}))
    monkeypatch.setattr(C, "load_config", lambda: {"curator_interval_hours": 24})
    monkeypatch.setattr(C, "log_target", lambda: log)
    called = {"n": 0}
    def model(prompt, manifest_json):
        called["n"] += 1; return "[]"
    C.main(now=NOW, run_claude=model, skills_dir=skills)
    assert called["n"] == 0
    ev = [e for e in R.read_events(log) if e["role"] == "curator"][-1]
    assert ev["outcome"] == "skipped" and ev["reason"] == "interval"


def test_dry_run_logs_the_proposal_and_changes_nothing(tmp_path, monkeypatch):
    # Makes preview a first-class, repeatable operation instead of a throwaway
    # script -- and it is the safe way to see what a 16-day-idle curator wants
    # to archive before letting it.
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "aged", learned_on="2026-06-01")
    monkeypatch.setattr(C, "load_config", lambda: {"curator_interval_hours": 0})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    monkeypatch.setattr(C, "log_target", lambda: log)
    rc = C.main(now=NOW, run_claude=lambda p, m: '[{"slug":"aged","op":"archive"}]',
                skills_dir=skills, dry_run=True)
    assert rc == 0
    assert (skills / "aged").exists()                    # nothing applied
    ev = [e for e in R.read_events(log) if e["role"] == "curator"][-1]
    assert ev["dry_run"] is True
    assert ev["would_apply"] == ["archive:aged"]
    assert ev["applied"] == []


def test_dry_run_does_not_advance_the_interval_clock(tmp_path, monkeypatch):
    # A preview must not consume the day's real run.
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "aged", learned_on="2026-06-01")
    monkeypatch.setattr(C, "load_config", lambda: {"curator_interval_hours": 24})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    monkeypatch.setattr(C, "log_target", lambda: log)
    C.main(now=NOW, run_claude=lambda p, m: "[]", skills_dir=skills, dry_run=True)
    assert not (skills / ".curator_state").exists()


def test_dry_run_flag_is_parsed_from_argv():
    assert C.parse_args(["--dry-run"])["dry_run"] is True
    assert C.parse_args([])["dry_run"] is False


def test_keep_decisions_are_counted_not_listed(tmp_path, monkeypatch):
    # "keep" is the common case; listing each one would bury the log. Counting it
    # still lets the numbers reconcile: proposed == kept + applied + skipped.
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "a", learned_on="2026-06-01")
    _mk(skills, "b", learned_on="2026-06-01")
    monkeypatch.setattr(C, "load_config", lambda: {"curator_interval_hours": 0})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    monkeypatch.setattr(C, "log_target", lambda: log)
    C.main(now=NOW, skills_dir=skills,
           run_claude=lambda p, m: '[{"slug":"a","op":"keep"},{"slug":"b","op":"archive"}]')
    ev = [e for e in R.read_events(log) if e["role"] == "curator"][-1]
    assert ev["proposed"] == 2 and ev["kept"] == 1
    assert ev["applied"] == ["archive:b"] and ev["skipped"] == []
    assert ev["proposed"] == ev["kept"] + len(ev["applied"]) + len(ev["skipped"])


def test_an_action_that_fails_to_apply_is_recorded_not_swallowed(tmp_path, monkeypatch):
    # Per-action failures used to vanish too; a failed archive must be visible.
    skills = tmp_path / "skills"; log = _log(tmp_path)
    _mk(skills, "aged", learned_on="2026-06-01")
    monkeypatch.setattr(C, "load_config", lambda: {"curator_interval_hours": 0})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    monkeypatch.setattr(C, "log_target", lambda: log)
    def bad_archive(md, root):
        raise OSError("read-only filesystem")
    monkeypatch.setattr(C, "archive", bad_archive)
    C.main(now=NOW, run_claude=lambda p, m: '[{"slug":"aged","op":"archive"}]',
           skills_dir=skills)
    ev = [e for e in R.read_events(log) if e["role"] == "curator"][-1]
    assert ev["applied"] == []
    assert ev["failed"][0]["slug"] == "aged"
    assert "read-only filesystem" in ev["failed"][0]["error"]
