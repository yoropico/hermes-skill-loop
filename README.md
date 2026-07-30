# hermes — a closed learning loop for Claude Code

Distills reusable procedures from your sessions into `~/.claude/skills/`, counts
which ones actually get used, and periodically curates them: archive the stale,
pin the proven, **never delete**.

The design is ported from the [Hermes Agent](https://github.com/NousResearch/hermes-agent)
Curator. The code is not — nothing here imports or shells out to Hermes, so its
version-ups cannot break this, and the intelligence rides on whatever Claude model
you point it at rather than on an algorithm frozen at port time.

## Install

```bash
/plugin marketplace add yoropico/hermes-skill-loop
/plugin install hermes
```

That is the whole installation. The plugin's own `hooks/hooks.json` owns its hooks —
**`~/.claude/settings.json` is never touched**.

Requires `python3` (3.9+; stdlib only) and the `claude` CLI on `PATH`.

### Migrating off the BCT-embedded version

If you previously ran this loop through the BCT terminal app, the old wiring must be
removed or both copies fire and every session end learns twice:

```bash
python3 ~/.claude/plugins/.../hermes/scripts/migrate-off-bct.py --dry-run
python3 ~/.claude/plugins/.../hermes/scripts/migrate-off-bct.py
```

It strips only the two hook entries that point at `~/.claude/scripts/skill-loop/`
(backing `settings.json` up first), removes that payload directory, and leaves your
learned skills and config alone. Idempotent.

**Deploy a BCT build with `SkillLoopDeploy` removed first.** The old deployer
overwrites `~/.claude/scripts/skill-loop` and re-merges its hooks on every launch,
so a stale BCT will undo the migration the next time it starts.

## What runs when

| Hook | Script | What it does |
|---|---|---|
| `SessionEnd` (async) | `learn.py` | Reads the transcript, asks the model whether a reusable procedure emerged, writes or updates one `SKILL.md` |
| `SessionEnd` (async) | `curator.py` | Interval-guarded (24h). Reviews learned skills and archives / pins |
| `PreToolUse` (`Skill`) | `usage.py` | Bumps `count` + `last_used` in `~/.claude/skills/.usage.json` |

Both `SessionEnd` hooks are `async`, so nothing delays session exit. Every nested
`claude -p` this loop spawns carries `SKILL_LOOP_INTERNAL=1`, and both `learn` and
`curator` no-op when they see it — otherwise each would re-trigger itself through
its own child's `SessionEnd`, unbounded.

## The firewall: `x-origin: skill-loop`

Learned skills carry `x-origin: skill-loop` in their frontmatter. **Everything
here operates only on marked skills.** Skills installed by other tools are
invisible: not curated, not archived, and never overwritten — `learn.py` refuses to
write a slug owned by someone else rather than clobbering it and stamping it as
ours.

`x-pinned: true` exempts a skill from archiving entirely.

## Is it working? — `/hermes doctor`

```
OK    python          3.9.6
OK    claude-cli      /Users/you/.local/bin/claude
OK    config          learn=claude-sonnet-5 curator=claude-opus-5
OK    log             /Users/you/.claude/skill-loop.jsonl
OK    hooks           1 hook event(s); last learn at 2026-07-30T00:10:30+00:00
OK    last-run        dry_run at 2026-07-29T23:57:43+00:00 (applied=[] skipped=0)
OK    reconciliation  63 proposed = 52 kept + 11 acted + 0 skipped
OK    skills          learned=63 never-used=31 listing~6140 tok
WARN  slugs           14 slug(s) sit exactly on the 40-char cap …
OK    descriptions    every learned skill has a description
```

Ten checks; exit 1 if any FAIL. The one that matters most is **`reconciliation`** —
for a healthy curator run `proposed == kept + acted + skipped`. When that arithmetic
breaks, the model's decisions are being dropped on the floor, which is precisely the
defect that made this loop a 16-day no-op. It is a check nobody had to be clever to
write; it just had to exist.

`hooks` uses the log as evidence rather than guessing: there is no way to introspect
Claude Code's active hook table, but a `learn` or `usage` event can only exist
because a hook fired.

## Run log — read this before believing the loop works

`~/.claude/skill-loop.jsonl` (override with `log_path`). One JSON object per line,
newest last, `role` = `learn` | `curator` | `usage`.

```bash
/hermes log
```

It exists because the first version of this loop **applied nothing at all for 16
days** (2026-07-14 → 07-30) while looking perfectly healthy: a bare
`except Exception: return []` returned the same empty list for a dead model id, an
unparseable reply, a pinned-skill veto, and a genuine "keep everything" — and
`.curator_state` stamped `last_run` either way. `outcome` separates those cases:

| `outcome` | meaning |
|---|---|
| `applied` | reached the apply phase; see `applied` / `failed` |
| `dry_run` | preview only; `would_apply` is what a real run would do |
| `skipped` + `reason: interval` | inside the 24h guard, model never called |
| `error` | the `claude -p` call raised — dead model id, missing binary, timeout |
| `unparseable` | reply had no JSON array; `raw_head` holds the first 200 chars |
| `empty` | no learned skills to curate |

`proposed == kept + len(applied) + len(skipped)` for a healthy run. If it does not
reconcile, actions are being dropped somewhere. Per-action skips carry a `reason`:
`pinned`, `too_young`, `not_a_learned_skill`, `unknown_op`.

The log is also the **only drift detector** for the Claude Code hook contract. If
`learn` starts logging `no_transcript_path` (with the `hook_keys` it did receive),
or `usage` logs `unreadable_skill_name`, a payload shape moved upstream. Both paths
used to just return 0, which is indistinguishable from a quiet, healthy loop.

Happy paths log nothing on purpose: the reentrancy sentinel and ordinary skill
invocations fire constantly and would bury everything worth reading.

## Preview before letting it act

```bash
/hermes curate --dry-run
```

Runs the real manifest through the real model and the real judgement, records
`would_apply`, changes nothing. `plan_actions()` is shared with the live path, so
the preview cannot drift out of agreement with what actually happens. A preview
ignores the interval guard (ask any time) and does not stamp `.curator_state` — it
must not consume the day's real run.

## Config: `~/.claude/skill-loop.json`

Entirely optional — every key falls back to a built-in default, so there is nothing
to seed and no bootstrap step.

| key | default | meaning |
|---|---|---|
| `enabled` | `true` | master kill switch, honoured by learn, usage and curator |
| `model` | `claude-sonnet-5` | shared model for both roles |
| `learn_model` | — | per-role override; learn runs every session end, so keep it cheap |
| `curator_model` | — | per-role override; curation is rare, so it can afford a stronger model |
| `curator_interval_hours` | `24` | minimum gap between real curator runs |
| `curator_min_age_days` | `7` | deterministic floor: never archive a skill younger than this, whatever the model proposes |
| `log_path` | `~/.claude/skill-loop.jsonl` | run log location |

`curator_min_age_days` is a code-level veto, not a prompt instruction: `count == 0`
is ambiguous between "stale" and "just born", so age is required before disuse means
anything.

## Tests

System `python3` may be 3.9 without pytest; run the suite under an isolated 3.11:

```bash
uv run --with pytest --python 3.11 python -m pytest tests/ -q
```

`tests/conftest.py` redirects the run log per-test, autouse. That is not politeness:
tests calling `main()` once forged ten events into the real
`~/.claude/skill-loop.jsonl`, and a diagnostic log the suite can forge is worse than
no log.

## License

MIT
