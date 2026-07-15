# .claude/skill-loop/tests/test_curator.py
import sys, pathlib, json
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
    skills = tmp_path / "skills"
    _mk(skills, "fresh", learned_on="2026-07-15")
    monkeypatch.setattr(C, "load_config",
                        lambda: {"curator_min_age_days": 7, "curator_interval_hours": 0})
    monkeypatch.setattr(C, "load_prompt", lambda: "PROMPT")
    def model(prompt, manifest_json):
        return '[{"slug":"fresh","op":"archive"}]'
    rc = C.main(now=NOW, run_claude=model, skills_dir=skills)
    assert rc == 0
    assert (skills / "fresh").exists()          # age floor vetoed the archive
