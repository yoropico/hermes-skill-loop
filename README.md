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
  runlog.py       append-only JSONL run log — every silent path writes here
  usage.py        PreToolUse(Skill) hook -> .usage.json
  learn.py        SessionEnd hook -> distill a SKILL.md via claude -p
  curator.py      idle review: archive/pin, never delete, marked-only
  bootstrap.py    merge hooks into settings.json + seed config
  config.default.json
  prompts/{learn,curate}.md
tests/            pytest (pure logic; claude -p is injected, never called)
```

## Run log — read this before believing the loop works

`~/.claude/skill-loop.jsonl` (override with `log_path`). One JSON object per line,
newest last, `role` = `learn` | `curator` | `usage`.

```bash
tail -5 ~/.claude/skill-loop.jsonl | python3 -m json.tool --json-lines   # recent activity
python3 - <<'PY'                                                          # curator history
import json, os
for l in open(os.path.expanduser("~/.claude/skill-loop.jsonl")):
    e = json.loads(l)
    if e["role"] == "curator":
        print(e["ts"], e["outcome"], "applied:", e.get("applied"), "skipped:", len(e.get("skipped", [])))
PY
```

It exists because the curator applied **nothing at all** for 16 days (2026-07-14
to 07-30) while `.curator_state` kept stamping `last_run`, and no artifact
anywhere could have told you. `outcome` distinguishes the cases that used to look
identical:

| `outcome` | meaning |
|---|---|
| `applied` | the run reached the apply phase; see `applied` / `failed` |
| `dry_run` | preview only; `would_apply` is what a real run would do |
| `skipped` + `reason: interval` | inside the 24h guard, model never called |
| `error` | the `claude -p` call itself raised — dead model id, missing binary, timeout |
| `unparseable` | the model replied without a JSON array; `raw_head` has the first 200 chars |
| `empty` | no learned skills to curate |

`proposed == kept + len(applied) + len(skipped)` for a healthy run — if it doesn't
reconcile, actions are being dropped somewhere. Per-action skips carry a `reason`
(`pinned`, `too_young`, `not_a_learned_skill`, `unknown_op`).

The log is also the **only drift detector** for the Claude Code hook contract.
`learn` logging `no_transcript_path` (with the `hook_keys` it did receive), or
`usage` logging `unreadable_skill_name`, means the SessionEnd / PreToolUse payload
shape moved upstream. Both paths used to just return 0.

Happy paths stay silent on purpose: the reentrancy sentinel and ordinary skill
invocations fire constantly and would bury everything worth reading. No rotation —
one line per session end is a few hundred bytes.

## Preview before letting it loose

```bash
python3 ~/.claude/scripts/skill-loop/curator.py --dry-run
```

Runs the real manifest through the real model and the real judgement, logs
`would_apply`, changes nothing. It ignores the interval guard (ask any time) and
does not stamp `.curator_state` (a preview must not consume the day's real run).
`plan_actions` is shared with the live path, so the preview cannot drift out of
agreement with what actually happens.

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

- `enabled` — master kill-switch (honored by learn/usage/curator + the BCT idle watcher).
- `model` — shared model for both learn and curator.
- `learn_model` / `curator_model` — optional per-role overrides (`<role>_model` > `model` > default `claude-sonnet-5`). learn runs on every session end, so it can stay cheaper; curation is rare (interval-guarded) and can afford a stronger model — e.g. `"model": "claude-sonnet-5"` + `"curator_model": "claude-opus-4-8"`.
- `idle_threshold_minutes`, `curator_interval_hours`, `curator_min_age_days`.
- `log_path` — override the run log location (default `~/.claude/skill-loop.jsonl`).

Edits to `~/.claude/skill-loop.json` are durable: `bootstrap.py` seeds it only when
missing and never overwrites an existing file.

## Tests

System `python3` is 3.9 without pytest; run the suite via uv (isolated 3.11):

```bash
uv run --with pytest --python 3.11 python -m pytest .claude/skill-loop/tests/ -q
```
