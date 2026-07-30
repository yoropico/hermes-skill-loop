# Changelog

## 1.0.0 — 2026-07-30

First standalone release. Extracted from the `bomi-terminal` (BCT) repo, where the
loop had been deployed by the terminal app itself.

### Changed from the BCT-embedded version

- **Installs as a Claude Code plugin.** `hooks/hooks.json` owns the SessionEnd and
  PreToolUse(Skill) hooks, so `~/.claude/settings.json` is never modified. Hook
  commands resolve through `${CLAUDE_PLUGIN_ROOT}` instead of absolute user paths.
- **`bootstrap.py` deleted.** Its two jobs are both gone: hook merging is the
  manifest's, and config seeding is unnecessary now that every key falls back to a
  built-in default.
- **Curator trigger moved to SessionEnd.** BCT drove it from a global-idle signal
  (`StatusbarBridge`, all panes quiet for 10 min) that does not exist outside that
  app. SessionEnd is by definition a moment work just stopped, and the 24h interval
  guard still bounds the cost.
- **Curator honours `SKILL_LOOP_INTERNAL`.** Required by the trigger change, and a
  real latent bug: the curator's own `claude -p` ends a session, firing SessionEnd,
  which would start another curator. The interval guard cannot stop that —
  `.curator_state` is stamped only *after* `curate()` returns, strictly later than
  the nested SessionEnd. `learn.py` has carried this sentinel since 2026-07-14; the
  curator never did, because the idle trigger made recursion impossible.
- Runs on any machine with `python3` and the `claude` CLI — no BCT, no macOS.

### Carried over

Run log (`runlog.py`), `curator.py --dry-run`, the `x-origin: skill-loop` firewall,
`curator_min_age_days` archive floor, per-role model overrides, autouse test
isolation. 89 tests.
