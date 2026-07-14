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
