# hermes skill loop — design of record

- **Status**: shipped, v1.1.0
- **Origin**: designed 2026-07-14 inside the `bomi-terminal` (BCT) repo as
  `docs/superpowers/specs/2026-07-14-skill-self-learning-loop-design.md`; extracted
  to this repo 2026-07-30. That document remains the historical record of the
  brainstorming; this one is authoritative from here on.
- **Reference pin**: the Curator design is ported from
  [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent)
  @ **`a4973c3f`**, released as **v0.19.0 (2026.7.20)**.

## Goal

Give one person a self-improving skill collection on top of Claude Code: the agent
distils reusable procedures from its own sessions, tracks which ones earn their
keep, and periodically curates the rest — archive the stale, pin the proven, merge
the duplicates, **never delete**.

## Why the design, not the code, was ported

Reusing Hermes itself was blocked and remains so: Anthropic routes third-party apps
to the metered extra-usage pool rather than plan limits (verified live, HTTP 400,
2026-07). More decisively, Hermes is a *separate agent* — its skills live in
`~/.hermes/skills/`, which Claude Code never reads, so a Hermes learning loop
improves Hermes and not the agent the work actually happens in.

Since the loop's intelligence lives in **prompts plus the model**, not in Hermes's
algorithm, porting the design onto Claude Code hooks gives three properties worth
more than reuse:

1. Code independence — Hermes version-ups cannot break this. Verified by grep: no
   `hermes` string appears anywhere in `scripts/`.
2. The intelligence axis improves for free — raise `curator_model` and distillation
   and curation get better with no algorithm work.
3. Hermes ideas remain absorbable as prompt diffs. Diff `agent/curator.py` over
   `a4973c3f..HEAD` and fold useful *perspectives* into `prompts/curate.md`. No
   local Hermes install is needed; the repo is public. The pin above is what makes
   that possible — before it was recorded, this path existed on paper only and was
   never once exercised.

## Components

| Module | Trigger | Purpose |
|---|---|---|
| `learn.py` | `SessionEnd` (async) | Read the transcript, ask the model whether a reusable procedure emerged, create or update one `SKILL.md` |
| `curator.py` | `SessionEnd` (async), 24h interval guard | Review learned skills; archive / pin / consolidate |
| `usage.py` | `PreToolUse` (`Skill`) | Bump `count` + `last_used` in `.usage.json` |
| `runlog.py` | — | Append-only JSONL record of everything above |
| `doctor.py` | manual (`/hermes doctor`) | Read that record and say when it does not add up |
| `skill_meta.py` | — | Frontmatter + the `x-origin` firewall |
| `migrate-off-bct.py` | one-time | Remove the BCT-era `settings.json` hooks and payload |

Prompts live as files (`prompts/{learn,update,curate,consolidate}.md`), never inline,
so absorbing an idea is a prompt edit with no code change.

## Two-stage learn

`learn.md` sees the transcript **plus an index of what we already know** and answers
create / update / nothing. On "update", `update.md` sees that skill's current text
and returns a merged body. Without stage two a later, better lesson forks a stale
twin instead of correcting the original — observed in the field before it existed.

## Safety invariants

1. **Never delete.** Archive is a move; pinned skills bypass archiving entirely.
2. **The marker is a firewall.** Only `x-origin: skill-loop` skills are touched.
   Anything else is invisible, and `learn.py` refuses to write a slug it does not own.
3. **Age floor before staleness.** `count == 0` is ambiguous between "stale" and
   "just born", so `curator_min_age_days` (default 7) is a deterministic code-level
   veto, not a prompt instruction the model may reason around.
4. **Reentrancy sentinel.** `SKILL_LOOP_INTERNAL=1` on every nested `claude -p`;
   both learn and curator no-op on it. The interval guard cannot substitute —
   `.curator_state` is stamped after `curate()` returns, later than the nested
   SessionEnd that would start round two.
5. **Non-blocking.** Both SessionEnd hooks are `async`; session exit is never delayed.

## Observability — the lesson that reshaped the design

The original design had no telemetry, and that turned a one-line defect into a
16-day silent outage. `prompts/curate.md` told the model to reply
`[{"slug":…,"op":…}]` while `apply_actions` read `act.get("skill")`; every proposed
action resolved to a `None` slug and was dropped — while `.curator_state` faithfully
stamped `last_run`, so "it ran" and "it worked" were indistinguishable. A bare
`except Exception: return []` returned the same empty list for a dead model id, an
unparseable reply, a pinned-skill veto, and a genuine "keep everything".

The response is structural:

- `curate()` **returns** the record that gets logged, so the log cannot disagree with
  the behaviour.
- `outcome` separates the previously identical cases: `applied` / `dry_run` /
  `skipped`+`reason` / `error` / `unparseable` / `empty`, with per-action skip
  reasons and per-action failures.
- **`proposed == kept + len(applied) + len(skipped)`.** Arithmetic, not judgement.
  One check would have caught the defect on day one; `doctor` now runs it.
- `plan_actions()` splits judgement from execution, so `--dry-run` runs the real
  decision rather than a parallel approximation free to drift.
- The log doubles as the only **hook-contract drift detector**: `learn` logging
  `no_transcript_path` (with the `hook_keys` it did receive) or `usage` logging
  `unreadable_skill_name` means an upstream payload shape moved. Both paths
  previously returned 0 — indistinguishable from a healthy, quiet loop.
- The test that hid the defect asserted only that a skill *survived* and credited the
  age floor for what was actually the key mismatch; it passed with the floor at 0
  too. It is now differential. **A test that cannot fail for the reason it claims to
  check is worse than no test.**

## Distribution

A Claude Code plugin. `hooks/hooks.json` owns the hooks via `${CLAUDE_PLUGIN_ROOT}`,
so `~/.claude/settings.json` is never modified and there are no absolute
user-specific paths. `bootstrap.py` was deleted rather than ported: hook merging
belongs to the manifest, and config seeding is unnecessary because every key falls
back to a built-in default.

The curator trigger moved from BCT's global-idle signal (`StatusbarBridge`, all panes
quiet for 10 minutes) to a second SessionEnd hook, because that signal does not exist
outside BCT. SessionEnd is by definition a moment work just stopped, and the interval
guard bounds the cost. The trade is real and recorded: BCT's signal knew when *nobody*
was working, whereas SessionEnd fires as one session closes while others may be busy.
If the log ever shows more than one real curation a day, or runs landing mid-work, the
middle path is for the plugin to consume BCT's idle signal when present and fall back
to SessionEnd otherwise — without BCT owning the code again.

## Non-goals

- No cross-machine skill sync, no sharing or publishing, no skill hub/bundles. This
  is a personal collection.
- No learning graph (Hermes `learning_graph.py`). Absorbable later as a prompt
  perspective rather than an algorithm port.
- No memory or user-profile features — `agentmemory` already owns that role, and two
  systems competing for it is worse than either alone.
- No agent-platform surface (gateway, chat integrations, cron, computer use). Out of
  scope: this loop learns, counts and curates.

## Known open items

- **Context cost is understood but unmanaged.** 63 learned skills price at ~6,100
  tokens of every session's listing, ~3,000 of it never used. `size_bytes` and
  `listing_tokens` now reach the curator, but nothing yet targets a budget.
- **Claude Code drops skill descriptions from its listing intermittently** (observed
  2026-07-30: the affected set changed mid-session with no file touched, and included
  unrelated third-party plugin skills). Not fixable here; `doctor`'s `descriptions`
  check keeps the file side correct, which is the part we own.
- **`learn` only fires at SessionEnd.** A long session that never ends contributes
  nothing. Hermes nudges skill creation every N turns; adopting that would add
  per-turn cost and needs evidence before it is worth it.
