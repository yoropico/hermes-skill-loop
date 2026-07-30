# Skill Self-Learning Loop — Design

- **Date**: 2026-07-14
- **Status**: **RELOCATED 2026-07-30** — shipped, then extracted out of BCT into the
  standalone plugin [`yoropico/hermes-skill-loop`](https://github.com/yoropico/hermes-skill-loop)
  (v1.0.0). This document remains the design of record for *why the loop works the
  way it does*; the four decisions about *where it lives and what starts it* are
  superseded below. Nothing about the loop ships in BCT any more.
- **Author**: bglee (via devmode/superpowers)
- **Worktree/branch**: `bomi-terminal-hermes-bct` / `hermes-bct`, then
  `curator-key-fix` → `curator-observ` → `hermes-plugin`

## Superseded decisions (2026-07-30)

| # | Was | Now | Why it changed |
|---|-----|-----|----------------|
| 3 | Developed in this BCT repo | Own public repo `yoropico/hermes-skill-loop` | The loop serves every Claude Code session on any machine; coupling its release to a macOS terminal app was accidental, not essential |
| 4 | Deployed by BCT on launch (`SkillLoopDeploy.swift`, payload folder-ref in the bundle) | `/plugin install hermes` | The plugin manifest owns the hooks, so `~/.claude/settings.json` is never modified and the absolute-path hook commands disappear |
| 6 | Curator triggered by BCT global idle (`StatusbarBridge`, all panes quiet 10 min) | Second `async` SessionEnd hook, same 24h interval guard | The idle signal does not exist outside BCT. SessionEnd is by definition a moment work just stopped, so no idle heuristic is needed |
| — | `bootstrap.py` merged hooks + seeded config | **Deleted** | Hook merging is the manifest's job; config seeding was never needed because every key already falls back to a built-in default |

Two consequences worth recording, because both were verified rather than assumed:

1. **Plugin `hooks.json` supports `matcher` and `async`.** Confirmed against
   installed plugins (devmode uses `matcher: "Bash"` and regex matchers;
   superpowers sets `async` explicitly). So `usage.py` keeps its `Skill` matcher
   and neither SessionEnd hook blocks session exit — no self-daemonising fork was
   required.
2. **Moving the curator to SessionEnd exposed a real latent bug.** `curator.py`
   never honoured `SKILL_LOOP_INTERNAL`, which `learn.py` has carried since
   PR #200. The curator's own `claude -p` ends a session → SessionEnd fires →
   curator again, and the interval guard cannot stop it because
   `.curator_state` is stamped only *after* `curate()` returns — strictly later
   than the nested SessionEnd. Unreachable under the idle trigger; live under a
   SessionEnd trigger. Fixed with a failing-test-first change in the new repo.

Also added after the original design, and carried into the plugin: a JSONL run log
(`runlog.py`) and `curator.py --dry-run`. See §Observability below — they exist
because the curator applied **nothing at all** for 16 days and no artifact could
have revealed it.

## Observability (added 2026-07-30)

The original design had no telemetry, and that turned a one-line defect into a
16-day silent outage: `prompts/curate.md` told the model to reply
`[{"slug":…,"op":…}]` while `apply_actions` read `act.get("skill")`, so every
proposed action resolved to a `None` slug and was dropped — while `.curator_state`
kept stamping `last_run`. A bare `except Exception: return []` returned the same
empty list for a dead model id, an unparseable reply, a pinned-skill veto, and a
genuine "keep everything".

The fix is structural, not cosmetic:

- `curate()` **returns** the record that gets logged, so the log cannot disagree
  with the behaviour.
- `outcome` separates the previously identical cases: `applied` / `dry_run` /
  `skipped`+`reason` / `error` / `unparseable` / `empty`, with per-action skip
  reasons and per-action failures.
- `proposed == kept + len(applied) + len(skipped)` is the reconciliation check that
  would have caught the original defect on day one.
- `plan_actions()` splits judgement from execution so `--dry-run` runs the *real*
  decision, not a parallel approximation free to drift.
- The log doubles as the loop's only **hook-contract drift detector**: `learn`
  logging `no_transcript_path` (with the `hook_keys` it did receive) or `usage`
  logging `unreadable_skill_name` means an upstream payload shape moved. Both paths
  previously just returned 0 — indistinguishable from a healthy, quiet loop.

## Goal

Give bglee a personal, self-improving skill loop on top of Claude Code — the
agent distills reusable procedures from sessions into `~/.claude/skills/`,
tracks their usage, and periodically curates them (consolidate / archive / pin,
never delete). Runs on the latest Claude (Max), deployed and triggered natively
by BCT.

## Background / motivation

Hermes Agent (NousResearch) ships a "closed learning loop" via its Curator.
Reusing Hermes on a Claude Max subscription is blocked: Anthropic routes
third-party apps to the metered "extra usage" pool, not plan limits (verified
live — HTTP 400). The Claude Agent SDK authenticates on the subscription but its
programmatic use draws a separate monthly Agent SDK credit, not unlimited plan
usage. Since the loop's *intelligence lives in prompts + the Claude model*, not
in Hermes code, we port the Curator's **design** (not its code) onto Claude Code
hooks. Result: code-independent from Hermes (can't break us), intelligence auto-
improves with newer Claude, and Hermes algorithm ideas are absorbed as light
prompt diffs (see Evolution Strategy).

Hermes Curator anatomy that we mirror (reference: `~/.hermes/hermes-agent`):
`learn_prompt.py` (distill nudge), `tools/skill_usage.py` (`.usage.json` +
`is_agent_created`), `agent/curator.py` (idle-triggered aux-model fork:
active→stale→archived, consolidate/patch/pin, never deletes, pinned bypass),
`agent/skill_commands.py` (scan + inject next session).

## Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Audience | Personal tool (bglee), any project |
| 2 | Artifact location | Global `~/.claude/` (skills, settings.json hooks, scripts) |
| 3 | Development | One repo — this BCT repo (hermes-bct worktree) |
| 4 | Deployment | Embedded in BCT app (`SkillLoopDeploy.swift`, on launch, mirroring the 7 existing SkillDeploy) |
| 5 | Learn trigger | Hybrid — SessionEnd hook → background `claude -p` self-judges whether a reusable procedure was learned |
| 6 | Curator trigger | BCT idle detection via StatusbarBridge (global idle → spawn curator) |
| 7 | Evolution | (A) Lightweight diff absorption — Hermes as reference only, absorb ideas as prompt diffs |

## Architecture

### Components (each = one purpose, one interface)

| # | Module | Location | Purpose · Interface |
|---|--------|----------|---------------------|
| ① | **learn hook** | `~/.claude/scripts/skill-loop/learn.py` | SessionEnd hook. In: hook JSON on stdin (`transcript_path`, `session_id`, `reason`, `cwd`). Reads transcript `.jsonl` → background `claude -p` self-judges "did I learn a reusable procedure?" → if yes, writes `~/.claude/skills/<slug>/SKILL.md` with the `x-origin` marker. Non-blocking (`async: true`, `nohup … &`). |
| ② | **usage tracker** | `~/.claude/scripts/skill-loop/usage.py` | PreToolUse(matcher `Skill`) hook. In: hook JSON (`tool_name`, `tool_input`). Bumps `count` + `last_used` in `~/.claude/skills/.usage.json`. Fast, synchronous, tiny. |
| ③ | **curator** | `~/.claude/scripts/skill-loop/curator.py` | Standalone script. In: none (scans `~/.claude/skills/` + `.usage.json` + `.curator_state`). Interval guard (default 24h) → `claude -p` reviews **agent-created skills only** → consolidate similar / archive stale / pin frequently-used. **Never deletes** (archive to `_archive/`). Pinned bypass. Writes `.curator_state.last_run`. |
| ④ | **idle trigger** | `Sources/SkillLoopDeploy.swift` + StatusbarBridge hook | Watches StatusbarBridge for global idle (all panes' `receivedAt` older than the idle threshold, default 10 min) → spawns `curator.py` via `Process()`. The interval guard lives in curator, so over-triggering is harmless. |
| ⑤ | **deploy** | `Sources/SkillLoopDeploy.swift` | On BCT launch (`BomiTerminalApp.deployAsync()`), writes ①②③ scripts + the prompt files + merges the SessionEnd/PreToolUse hook entries into `~/.claude/settings.json`. Mirrors the existing 7 `*SkillDeploy.swift`. Idempotent; guarded by a `SkillSyncTests`-style sync test pinning embedded strings to repo source. |
| ⑥ | **marker** | SKILL.md frontmatter | Learned skills carry `x-origin: skill-loop`. Curator and archive operate ONLY on marked skills. BCT's 7 deployed skills (unmarked, re-deployed every launch) are invisible to the curator. |

### Prompt externalization

learn/curator prompts live as `~/.claude/scripts/skill-loop/prompts/{learn,curate}.md`
(repo source under `.claude/skill-loop/prompts/`), NOT hardcoded in Python or
Swift — so an evolution diff (§Evolution) is a prompt edit, no rebuild.

### Data flow

```
work → SessionEnd hook → learn.py → claude -p judges → SKILL.md (x-origin marker) → ~/.claude/skills/
skill used → PreToolUse(Skill) hook → usage.py → .usage.json
BCT global idle (StatusbarBridge) → SkillLoopDeploy spawns curator.py (interval-guarded) → claude -p review → archive/consolidate/pin (marked skills only)
next session → Claude Code auto-loads ~/.claude/skills/   ← loading is free (built-in)
```

## Safety invariants

1. **Protect BCT-deployed skills.** Curator touches only `x-origin: skill-loop`
   skills. BCT's 7 skills are re-deployed on every launch; if the curator
   archived one it would fight the deploy forever. The marker is the firewall.
2. **Never delete.** Archive to `~/.claude/skills/_archive/`; recoverable.
   Pinned skills bypass all auto-transitions.
3. **Idle threshold generous** (10 min) so the curator never runs while bglee is
   actively working (cost + noise). The interval guard (24h) is a second gate.
4. **Non-blocking learn.** `async: true` + `nohup claude -p &`; never delays
   session exit.

## Verified hook contracts (risks resolved)

Verified against `https://code.claude.com/docs/en/hooks.md` (claude-code-guide)
and BCT source.

1. **SessionEnd** receives `{session_id, transcript_path, cwd, hook_event_name,
   reason}` on stdin; `transcript_path` gives the full `.jsonl`. **Caveat**: the
   transcript is written asynchronously and may lag — learn.py must tolerate a
   short flush delay / truncation (retry with small backoff). SessionEnd is
   side-effect-only (cannot alter behavior), which is fine for us.
2. **PreToolUse fires for Skill invocations** (*"Skills are invoked as tool
   calls, so PreToolUse fires"*); match `tool_name == "Skill"`, read
   `tool_input`. Usage counting is viable.
3. **SessionEnd, not Stop.** Stop fires per-turn; SessionEnd fires once at
   session end and carries `transcript_path`.
4. **Background + timeout.** `async: true` runs non-blocking; default hook
   timeout 600s applies even to async (extend via `timeout`). Use `nohup … &`.
5. **BCT spawn.** BCT already spawns processes via `Process()`
   (TmuxService/BctDeploy/SpotlightHygiene); StatusbarBridge exposes
   `onPayload: ((UUID)->Void)?` and `panes[UUID: PaneState].receivedAt` — enough
   to derive global idle and spawn the curator.

## Defaults (config-adjustable)

- Idle threshold: **10 min** · Curator interval: **24 h**
- Learn + curate model: **Sonnet** (Haiku degrades quality; promotable to Opus
  via config)
- Config file: `~/.claude/skill-loop.json` (thresholds, model, enabled flag)

## Evolution strategy (A)

- **Reference version pin** (recorded 2026-07-30): upstream
  `NousResearch/hermes-agent` @ **`a4973c3f`**, released as **v0.19.0 (2026.7.20)**.
  That is the last revision this design was checked against. To absorb later
  Hermes work, diff `agent/curator.py` over `a4973c3f..HEAD` and fold useful
  *perspectives* into `prompts/curate.md` — a prompt edit, not an algorithm port,
  no Swift rebuild. ~a few times/year.
  - **No local Hermes install is required for this.** The reference checkout at
    `~/.hermes` was removed on 2026-07-30 (it is a separate agent whose skills
    live in `~/.hermes/skills`, which Claude Code never reads, so it could not
    serve this loop). The repo is public — fetch the diff on demand. The pin
    above is what makes that possible; before it was recorded, this whole
    absorption path existed only on paper and was never once exercised.
- **Intelligence axis is automatic**: bumping the model (Sonnet → Opus → next)
  improves distillation/curation with zero Hermes tracking. We run the latest
  Claude — likely ahead of Hermes's open-model backend.
- **Code stays decoupled** from Hermes: version-ups can't break us.

## Testing

- `SkillLoopSyncTests` (XCTest, mirrors `SkillSyncTests`): embedded deploy
  strings == repo source for scripts + prompts + hook-merge JSON.
- Pure-logic unit tests (Python or Swift host): marker filtering (unmarked
  skills invisible to curator), interval guard, global-idle predicate over a
  synthetic `panes` map, never-delete (archive path only), pinned bypass.
- `settings.json` hook-merge idempotency (re-deploy doesn't duplicate entries).
- Manual live smoke: run a throwaway session → confirm SessionEnd learn fires,
  a marked SKILL.md appears; force idle → curator runs once, respects interval.

## Non-goals (YAGNI)

- No cross-machine skill sync, no sharing/publishing, no learning-graph port
  (Hermes `learning_graph.py`) in v1 — absorbable later as a prompt perspective.
- No BCT-product-facing feature (this is a personal tool; unmarked BCT skills
  are untouched).
- No idle daemon — BCT is already running and owns the idle signal.

## Open items to settle in the plan

- Exact global-idle predicate (empty `panes` vs all `receivedAt` > threshold)
  and where the watcher timer lives (SkillLoopDeploy vs OverlayComposer tick).
- learn.py transcript-flush handling (delay vs poll-until-stable).
- `settings.json` merge strategy that coexists with any user-managed hooks.
