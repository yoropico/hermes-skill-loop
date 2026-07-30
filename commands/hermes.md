---
name: hermes
description: Inspect and drive the hermes skill loop — preview what the curator would archive, read the run log, or curate now.
---

# hermes

Drive the skill self-learning loop. Arguments: `$ARGUMENTS`

Interpret the argument and do exactly one of the following. With no argument, do `status`.

## `status`

Report the loop's actual state. Do not guess — read it:

```bash
CFG=~/.claude/skill-loop.json
LOG=$(python3 -c "import sys;sys.path.insert(0,'$CLAUDE_PLUGIN_ROOT/scripts');import runlog;print(runlog.log_path())")
echo "config:"; cat "$CFG" 2>/dev/null || echo "  (none — bundled defaults in use)"
echo "learned skills: $(grep -rl 'x-origin: skill-loop' ~/.claude/skills/*/SKILL.md 2>/dev/null | wc -l | tr -d ' ')"
echo "archived:       $(ls ~/.claude/skills/_archive 2>/dev/null | wc -l | tr -d ' ')"
echo "last curator run: $(cat ~/.claude/skills/.curator_state 2>/dev/null || echo none)"
echo "log: $LOG ($(grep -c '' "$LOG" 2>/dev/null || echo 0) events)"
```

Then summarise the last few log events. Call out anything alarming: an `error` or
`unparseable` outcome, or a `proposed` count that does not reconcile with
`kept + applied + skipped` — that means actions are being dropped.

## `curate --dry-run` (or `preview`)

Ask the curator what it would do, without letting it:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/curator.py" --dry-run
```

It ignores the 24h interval guard and never stamps the clock, so a preview is
always safe and never consumes the day's real run. Read the resulting `dry_run`
event from the log and present `would_apply` as two lists — archives and pins —
with each skill's usage count and age, so the user can judge before applying.

## `curate` (apply for real)

Only when the user clearly wants the actions applied. Show them the dry-run
result first if you have not already.

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/curator.py"
```

Then report the `applied` / `skipped` / `failed` from the log. Archiving is a move
to `~/.claude/skills/_archive/` — recoverable, never a delete.

## `log [N]`

Show the last N (default 10) events, newest last:

```bash
python3 - <<'PY'
import json, os, sys
sys.path.insert(0, os.environ["CLAUDE_PLUGIN_ROOT"] + "/scripts")
import runlog
for e in runlog.read_events()[-10:]:
    print(e["ts"], e["role"], e.get("outcome"), e.get("reason") or e.get("error") or "")
PY
```

## Notes

- The loop only ever touches skills marked `x-origin: skill-loop`. Skills deployed
  by other tools are invisible to it — do not offer to curate those.
- `enabled: false` in `~/.claude/skill-loop.json` is a real kill switch honoured by
  learn, usage and the curator alike.
