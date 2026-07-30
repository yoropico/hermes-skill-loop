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

## 1.1.0 — 2026-07-30

Priority-ordered follow-ups to the extraction. 130 tests (was 89).

### Added

- **`/hermes doctor`** — ten checks over environment, config, run log and skill
  store; exit 1 on any FAIL. The one that justifies it is `reconciliation`:
  `proposed == kept + acted + skipped`. The 16-day no-op produced runs where a
  dozen actions evaporated; that is arithmetic, not judgement, and one check would
  have caught it on day one. `hooks` uses the log as evidence rather than guessing —
  Claude Code's active hook table cannot be introspected, but a `learn`/`usage`
  event can only exist because a hook fired.
- **`consolidate` op** — the one the original design promised and never shipped.
  Merges a skill's body into another via a second model pass told to lose nothing,
  then archives it with `x-consolidated-into`. The merge must succeed *before*
  anything moves: archiving first would, on a failed merge, leave the knowledge
  only in `_archive/`. Requires `into`; refuses self/unknown/foreign targets; obeys
  the pinned bypass and age floor; `--dry-run` returns before any merge call.
  Without it, `archive` was the only tool for two overlapping skills — and it
  discards whatever the weaker one knew that the survivor did not.
- **Cost signals** — `size_bytes` and `listing_tokens` per manifest entry,
  `total_bytes` / `total_listing_tokens` in the log. `listing_tokens` is the
  standing price: every skill's `slug: description` is injected into every session
  whether used or not. The curator had been weighing usefulness with no idea what
  anything cost.

### Fixed

- **Slugs no longer cut mid-word.** The 40-char cap was a hard slice, producing
  live names like `chromium-extension-indexeddb-offline-rea` (14 of them). The slug
  is a matching signal, so a severed final word is worse than no final word —
  truncation now drops the whole unfinished token, falling back to a hard cut only
  when there is no boundary (one very long word).
- **Legacy slugs stay resolvable.** `learned_skill_path` and `write_skill` check the
  old hard-cut name too, and an existing skill of ours always wins over a fresh
  slug. Without this the truncation change would have quietly stopped finding those
  14 skills, and every later lesson would have forked a stale twin beside the
  original — the exact failure the two-stage learn exists to prevent.

### Investigated, unresolved

Five learned skills render in Claude Code's session listing with **no description**,
making them unmatchable while still costing a listing line. Our side is clean and
provably so: the descriptions are present in every file, and on every measurable
dimension — frontmatter key set, key count, description length, line count, colons,
quotes, CRLF, BOM, byte layout — the five are indistinguishable from skills whose
descriptions do render, with fully overlapping ranges. No user-skill index or cache
exists to hold a stale copy. The omissions are interleaved alphabetically, so it is
not a listing cutoff. Cause is in Claude Code's system-prompt assembly and is not
observable from here; `doctor`'s `descriptions` check confirms the file side stays
correct.
