## curator-key-fix — code done, gate green, live rollout PENDING yoros
- Updated: 2026-07-30
- Branch: curator-key-fix (worktree ../worktrees/bomi-terminal-curator-key-fix)

### Done
- **Hermes (real NousResearch agent) fully removed.** v0.19.0 was installed 7/14 + updated 7/30 06:57 from
  another session. It is a separate agent (skills in `~/.hermes/skills`, unreadable by Claude Code), so it
  could not serve the `~/.claude/skills` loop. Removed via the supported non-interactive entrypoint
  `python -m hermes_cli.uninstall --mode lite` (the `hermes uninstall` CLI hard-gates on `stdin.isatty()`),
  run under an external uv python 3.12, then `rm -rf ~/.hermes`. 1.2G reclaimed, no residue. BCT's
  skill-loop verified untouched.
- **Curator no-op fixed (TDD).** `prompts/curate.md` emits `{"slug":…}`, `apply_actions` read
  `act.get("skill")` → every action silently dropped since the first commit (152b8e69, 7/14). Fix accepts
  both keys. `curator.py:139`.
- **The false-green test that hid it, corrected.** `test_main_threads_configured_age_floor` asserted only
  survival and credited the age floor; it passed with `min_age_days=0` too. Now differential (floor 7
  vetoes / floor 0 really archives) + a new contract test that parses `curate.md`'s reply shape and asserts
  the applier honours that key.
- **Gate green**: 55 pytest (was 53); full BCT `xcodebuild test` — XCTest 902/0, Swift Testing 3217 tests /
  403 suites, `** TEST SUCCEEDED **`, rc=0; py3.9 import + py_compile OK.
- Committed on branch `curator-key-fix`. NOT pushed, NOT landed.

### Deliberately NOT done — needs yoros's call
1. **Live deploy.** Three targets, only the repo is current:
   `~/.claude/scripts/skill-loop/curator.py` and
   `/Applications/BCT.app/Contents/Resources/scripts/curator.py` still carry `act.get("skill")`.
   Payload-only change → no Swift rebuild needed (PR #207 precedent), but the bundle must be patched via
   ditto-to-staging → patch + codesign there → `rm -rf` + ditto into /Applications. Apple Development
   signing only (`K83K59TGLX`), never adhoc.
2. **Archive blast radius.** Once deployed, the next idle curator run really moves skills into `_archive/`.
   32 of 63 learned skills have never been used and most are past the 7-day floor. Options put to yoros:
   (a) dry preview first — build the real manifest, get the model's proposal, review the archive list
   before applying; (b) just let it run (recoverable — archive is a move).

### Known-but-out-of-scope (found while investigating, not fixed)
- No observability: `curate()` swallows every exception and returns `[]`; no log anywhere. This is WHY a
  16-day no-op went unnoticed. A JSONL run log (proposed / applied / skipped+reason / model / duration) is
  the obvious follow-up.
- Spec promised a `consolidate` op; only `archive`/`pin` exist → duplicate skills accumulate forever.
- Curator manifest carries no size signal; 43KB (`devmode-task-worktree-pitfalls`) and 20KB skills are
  invisible as context hogs.
- 5 skills render in the session listing with NO description (`self-hosted-api-offsite-unreachable-diag`,
  `sentinelone-api-fp-exclusion-and-resolve`, `timer-driven-veto-guard-review`,
  `web-widget-missing-cdn-subdomain-block-d`, `windows-gpo-audit-csv-whole-machine-poli`) → effectively
  unmatched. Their SKILL.md files DO have descriptions and are byte-structurally identical to working
  ones; root cause unknown.
- Learned-skill descriptions cost ≈6.1K tokens of every session's listing, ≈3K of it never-used.
