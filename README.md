# Skill self-learning loop (Python core)

Personal loop that distills reusable procedures from Claude Code sessions into
`~/.claude/skills/`, tracks their usage, and curates them (archive/pin, never
delete). Learned skills are marked `x-origin: skill-loop`; BCT-deployed skills
(unmarked) are never touched.

Spec: `docs/superpowers/specs/2026-07-14-skill-self-learning-loop-design.md`
Plan: `docs/superpowers/plans/2026-07-14-skill-loop-1-python-core.md`

## Layout

```
scripts/
  skill_meta.py   frontmatter + x-origin marker helpers (the firewall)
  usage.py        PreToolUse(Skill) hook -> .usage.json
  learn.py        SessionEnd hook -> distill a SKILL.md via claude -p
  curator.py      idle review: archive/pin, never delete, marked-only
  bootstrap.py    merge hooks into settings.json + seed config
  config.default.json
  prompts/{learn,curate}.md
tests/            pytest (pure logic; claude -p is injected, never called)
```

## Manual install (Plan 2 automates this via BCT on launch)

```bash
mkdir -p ~/.claude/scripts/skill-loop
cp -R .claude/skill-loop/scripts/* ~/.claude/scripts/skill-loop/   # scripts + prompts/ + config.default.json
python3 ~/.claude/scripts/skill-loop/bootstrap.py                  # merge hooks, seed ~/.claude/skill-loop.json
```

`bootstrap.py` is idempotent — re-running never duplicates hook entries and
never overwrites an existing `~/.claude/skill-loop.json`. It preserves any hooks
you already have in `settings.json`.

## Curator (until Plan 2's BCT idle trigger exists, run it by hand)

```bash
python3 ~/.claude/scripts/skill-loop/curator.py   # interval-guarded (24h)
```

## Config: `~/.claude/skill-loop.json`

`enabled`, `model` (learn/curate model), `idle_threshold_minutes`,
`curator_interval_hours`.

## Tests

System `python3` is 3.9 without pytest; run the suite via uv (isolated 3.11):

```bash
uv run --with pytest --python 3.11 python -m pytest .claude/skill-loop/tests/ -q
```
