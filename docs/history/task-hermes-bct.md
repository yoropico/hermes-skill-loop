## Session state (devmode)
- Updated: 2026-07-15
- Goal: Skill self-learning loop on Claude Code, natively integrated with BCT
- Branch: hermes-bct (PRs #198, #200, #201, #207 — all merged)
- Status: **LIVE + SELF-CORRECTING** — loop shipped, 12 skills learned in the wild, audited, and the
  audit's findings fed back into the loop itself (PR #207).

### Mental model
Port of the Hermes Curator DESIGN (not code) onto Claude Code hooks. A personal
loop: distill reusable procedures from sessions -> ~/.claude/skills/, track
usage, curate (archive/pin, never delete). Learned skills carry `x-origin:
skill-loop` (the firewall — BCT's deployed skills are untouched). Runs on the
latest Claude; Hermes version-ups absorbed as prompt diffs, not code.

### Decisions (locked)
Personal tool · artifacts in ~/.claude/ · dev in BCT repo · deploy via BCT app
bundle folder-ref · learn = hybrid (SessionEnd -> bg `claude -p` self-judge) ·
curator = BCT global-idle (StatusbarBridge) · evolution = prompt-diff absorption.

### Gotchas (carry forward)
- System python is 3.9 (no pytest) -> tests via `uv run --with pytest --python 3.11 python -m pytest`;
  BUT deployed scripts must stay 3.9-compat (app runs `/usr/bin/env python3`) — verified via py_compile.
- prompts/ + config.default.json live UNDER scripts/ (matches code load paths). repo-run == deployed-run.
- `SkillLoopDeploy.deploy()` REPLACES ~/.claude/scripts/skill-loop from the bundle on EVERY app launch.
  Patching only ~/.claude is transient — the bundle must carry the change too, or a restart reverts it.
- Safe way to patch the bundle while BCT may be running: ditto a staging copy, patch + `codesign` THERE,
  then `rm -rf` + ditto into /Applications. Never re-sign the running bundle in place (rewrites the mapped
  executable). Verify `Authority=Apple Development` + `flags=0x0(none)` — adhoc breaks the bomi IME.
- `git rebase origin/master` ALWAYS conflicts on .claude/worklog.md (both sides append at the same tail).
  Resolve: `git checkout --ours` then re-append your own lines. Do not fight it with stash.
- No MCP session tools here + REST /save is stale -> THIS FILE + worklog ARE the notebook.

### Files
- `.claude/skill-loop/scripts/{skill_meta,usage,learn,curator,bootstrap}.py`,
  `scripts/prompts/{learn,update,curate}.md`, `scripts/config.default.json`, `tests/test_*.py`
- `Sources/SkillLoopDeploy.swift` (bundle deploy + idle watcher), `Tests/SkillLoopDeployTests.swift`
- `docs/superpowers/specs/2026-07-14-skill-self-learning-loop-design.md`, plans `2026-07-14-skill-loop-{1,2}-*.md`

### Current state (2026-07-15)
- origin/master = `64feba6` (PR #207 merged). /Applications/BCT.app: Swift = `fb22d96` (Info.plist GitCommit),
  payload = patched to #207 + Apple-Dev re-signed (verified VALID, flags=none). #207 has NO Swift change, so the
  deployed app is functionally equivalent to master — no rebuild pending.
- `~/.claude/scripts/skill-loop/` patched live (2-stage learn + update.md); imports clean on python 3.9.
- 12 learned skills in ~/.claude/skills/, all `x-origin: skill-loop`; 4 of them already re-used per `.usage.json`.
  Curator last ran 2026-07-14 01:57Z, before most of them existed — it has never yet seen the current corpus.

### Audit of the learned corpus (2026-07-15) — what it found
- Distiller is HONEST: 12/12 contract-compliant, no secrets/personal-path leaks, and zero hallucinations in the
  verifiable set (spot-checked `task.js --migrate` and the `customTitle` transcript record — both real).
- The LOOP was the broken part, not the distills. Fixed in #207:
  1. learn could only `create`, never `update`, and never saw its own back-catalogue -> better lessons forked
     stale twins. Now 2-stage: index -> `{"update": "<name>"}` -> `update.md` returns the merged full body.
  2. FIREWALL HOLE: `write_skill()` overwrote by slug alone — a distilled name colliding with a BCT-deployed
     skill would have destroyed it and stamped it `x-origin: skill-loop`. Now refuses any path we did not author.
  3. `x-learned` / `x-source` frontmatter (provenance was un-auditable).
  4. Prompt rules: runnable commands (placeholders in `<>`), guarded form of destructive/shared-state commands.
- Hand-fixed the one defective skill: `~/.claude/skills/bct-redeploy-to-applications` taught a bare
  `git stash push`/`drop` on a stash stack SHARED across worktrees + concurrent sessions (can destroy another
  session's work) and embedded a fake ref `local_stash_ref`. Rewrote it: detached-worktree build is now the
  primary path (avoids the worklog conflict entirely), stash fallback is tagged + apply-by-SHA.

### Curator age-floor (2026-07-15, item #2 DONE — UNCOMMITTED in repo)
Forced a curator dry-run (opus-4-8) over the live 19-skill corpus. Verdict: judgments SANE — 0 archives,
1 correct pin (bct-redeploy, count=4). But the run exposed a real gap: the manifest had NO age signal, so
the model could not distinguish a fresh count=0 skill from a genuinely stale one; curate.md's "unused for a
long time" was unenforceable. Fixed:
- Applied the proposed pin → `~/.claude/skills/bct-redeploy-to-applications` now `x-pinned: true` (LIVE).
- `curator.build_manifest(skills_dir, now)` emits `age_days` per skill (x-learned frontmatter, mtime fallback).
- `curator.apply_actions(..., min_age_days, now)` enforces a floor (`curator_min_age_days`, default 7): archiving
  a skill younger than the floor is vetoed IN CODE regardless of the model's proposal — deterministic firewall,
  not just a prompt rule. curate.md + config.default.json updated.
- 6 new tests in test_curator.py; 53/53 skill-loop tests green; py_compile 3.9 OK. Real corpus: all 19 skills
  age 0-1d → every archive currently vetoed (exactly intended).
DEPLOY STATE: LANDED via its own follow-up task/PR — **PR #213 merged to master** (branch curator-age-floor,
now deleted; task archived to sessions/done/). Also **live-patched** ~/.claude/scripts/skill-loop (curator.py
+ config.default.json + curate.md) so the running loop enforces the floor immediately. STILL PENDING: the BCT
app bundle does not yet carry it — SkillLoopDeploy copies bundle→~/.claude on launch, so a BCT rebuild+redeploy
is needed or the next app launch reverts the live patch. Deferred to the next BCT deploy (yoros's call).

### Next (pick up here)
1. **Watch the update path fire in the wild** — after a few sessions, look for a skill whose `x-learned` date is
   newer than its neighbours (that's an update, not a create). If the model NEVER chooses `{"update": ...}`,
   the index in the prompt is probably too terse to recognise overlap — feed it more than name+description.
2. ~~Curator has never seen the current corpus~~ DONE (see "Curator age-floor" above). Follow-up: re-run the
   dry-run once the corpus has skills older than the 7d floor, to confirm archive judgments are still sane when
   staleness becomes *possible* (right now nothing can be archived).
3. The skill corpus and `~/.claude/memory/` now hold overlapping facts (e.g. the recursion-guard lesson lives in
   both) and neither knows about the other. Decide whether that's acceptable duplication or needs a bridge.
4. Evolution: on `hermes update`, diff Hermes `curator.py` and absorb useful perspectives (e.g. learning-graph)
   into curate.md — see Plan 2 §Implementation notes / spec §Evolution.

### Open
- None blocking.
