# hermes-skill-loop

A closed learning loop for Claude Code, shipped as a plugin. Three hooks distil
reusable procedures from sessions into `~/.claude/skills/`, count which ones get
used, and curate the collection. Extracted from the `bomi-terminal` (BCT) repo on
2026-07-30, where BCT used to deploy it on launch.

Design of record: `docs/SPEC.md`. How to use it: `README.md`.

## Invariants — break these and the loop quietly stops being trustworthy

1. **Never delete a skill.** Archiving is a move to `~/.claude/skills/_archive/`.
   Every destructive-looking op must be recoverable.
2. **`x-origin: skill-loop` is a firewall, not a label.** Only marked skills are
   ever read, curated, archived or overwritten. Skills installed by other tools
   must stay invisible — `learn.py` refuses to write a slug it does not own rather
   than clobbering it and stamping it as ours.
3. **Every silent path writes to the run log.** A swallowed exception, a skipped
   action, an unreadable hook payload. This loop already spent 16 days applying
   nothing while looking healthy; a new quiet failure mode is the one regression
   that matters most here. If you add an early `return`, ask what records it.
4. **`runlog.emit` may never raise.** It instruments the hooks; if it can break
   them it has become an instance of the problem it exists to expose.
5. **The prompt and the code must agree, and a test must enforce it.** The original
   defect was `prompts/curate.md` telling the model to emit `{"slug": …}` while
   `apply_actions` read `act.get("skill")` — every action silently dropped for 16
   days. `test_prompt_reply_key_is_honoured_by_the_applier` and
   `test_the_prompt_documents_every_op_the_planner_accepts` read the prompt files
   and fail on drift. Keep that pattern when adding an op or changing a reply shape.
6. **Tests never touch `$HOME`.** `tests/conftest.py` redirects the run log
   autouse. Tests once forged ten events into the real log — the very artifact you
   consult to learn what the loop did.
7. **Reconciliation must hold:** `proposed == kept + len(applied) + len(skipped)`.
   `doctor` checks it. If a new op can leave an action unaccounted for, the op is
   wrong, not the check.

## Hard constraints

- **python3 stdlib only, 3.9-compatible.** The hooks run under whatever `python3`
  resolves to, and macOS ships 3.9.6. No third-party imports, and no PEP 604
  (`X | None`) in a position evaluated at runtime — `from __future__ import
  annotations` is already at the top of every module; keep it there.
- **`SKILL_LOOP_INTERNAL=1` on every nested `claude -p`,** and both `learn.py` and
  `curator.py` must no-op when they see it. Each spawns a session whose SessionEnd
  fires these same hooks; without the sentinel each re-triggers itself unbounded.
  The 24h interval guard does NOT substitute — `.curator_state` is stamped only
  after `curate()` returns, strictly later than the nested SessionEnd.
- **Slugs: never rename an existing skill directory.** The 40-char cap now cuts at
  a word boundary, so `slugify` and the legacy hard cut disagree for long names.
  `learned_skill_path` and `write_skill` try both, existing-ours-wins. Drop that and
  every later lesson forks a stale twin beside the original.
- **A `--dry-run` must not call a mutating model pass.** `curate()` returns before
  any consolidate merge. A preview that rewrites the survivor is not a preview.
- **Consolidate merges before it moves.** Archiving first would, on a failed merge,
  leave the knowledge only in `_archive/`.

## Build / test

```bash
uv run --with pytest --python 3.11 python -m pytest tests/ -q   # system py3.9 has no pytest
cd scripts && python3 -c "import runlog, curator, learn, usage, skill_meta, doctor"
python3 -m py_compile scripts/migrate-off-bct.py
```

CI runs the suite on 3.9 and 3.12 plus a manifest-consistency check. Bump
`version` in **both** `.claude-plugin/plugin.json` and the `metadata.version` of
`.claude-plugin/marketplace.json`, and add a CHANGELOG entry.

## Live verification

The suite cannot prove the hooks are wired. Two things do:

- `usage.json` increments by exactly one when a skill is invoked → the
  `PreToolUse(Skill)` hook fired, once (not twice).
- A `learn` or `usage` event in `~/.claude/skill-loop.jsonl` → a hook ran.
  `doctor`'s `hooks` check uses precisely this, because Claude Code's active hook
  table cannot be introspected.

To exercise the hook commands exactly as the manifest spells them without touching
the real store, run them with an isolated `HOME` and `CLAUDE_PLUGIN_ROOT` pointed at
the checkout.

## Work log

`.claude/worklog.md` — one line per decision, the WHY not the what. English, like
every other dev artifact here. User-facing replies are Korean.
