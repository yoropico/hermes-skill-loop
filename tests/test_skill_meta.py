import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import skill_meta as m
from pathlib import Path


def _write(p: Path, body: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


LEARNED = "---\nname: foo\ndescription: d\nx-origin: skill-loop\n---\n\n# Foo\n"
PLAIN   = "---\nname: bar\ndescription: d\n---\n\n# Bar\n"
NOFM    = "# Just a heading\n"


def test_read_frontmatter_parses_keys(tmp_path):
    p = tmp_path / "a" / "SKILL.md"; _write(p, LEARNED)
    fm = m.read_frontmatter(p)
    assert fm["name"] == "foo" and fm["x-origin"] == "skill-loop"


def test_read_frontmatter_none_when_absent(tmp_path):
    p = tmp_path / "b" / "SKILL.md"; _write(p, NOFM)
    assert m.read_frontmatter(p) is None


def test_is_learned_true_only_with_marker(tmp_path):
    a = tmp_path / "a" / "SKILL.md"; _write(a, LEARNED)
    b = tmp_path / "b" / "SKILL.md"; _write(b, PLAIN)
    assert m.is_learned(a) is True and m.is_learned(b) is False


def test_is_pinned(tmp_path):
    p = tmp_path / "c" / "SKILL.md"
    _write(p, "---\nname: c\nx-origin: skill-loop\nx-pinned: true\n---\n")
    assert m.is_pinned(p) is True


def test_list_learned_skips_unmarked_and_archive(tmp_path):
    skills = tmp_path / "skills"
    _write(skills / "keep" / "SKILL.md", LEARNED)
    _write(skills / "bct-native" / "SKILL.md", PLAIN)         # unmarked BCT skill
    _write(skills / "_archive" / "old" / "SKILL.md", LEARNED)  # archived
    got = {p.parent.name for p in m.list_learned(skills)}
    assert got == {"keep"}
