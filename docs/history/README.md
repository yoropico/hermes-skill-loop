# history — where this came from

This loop was designed and built inside the [`bomi-terminal`](https://github.com/yoropico/bomi-terminal)
(BCT) repo between 2026-07-14 and 07-30, as `.claude/skill-loop/`, deployed by the
BCT terminal app on launch. It was extracted into this repo on 2026-07-30.

These files are the originals, copied verbatim so the reasoning lives here and not
one repo away. They are **historical record, not current documentation** — where they
disagree with `docs/SPEC.md`, `CLAUDE.md` or `README.md`, those win.

| file | what it is |
|---|---|
| `2026-07-14-original-design-spec.md` | The brainstorming spec. Its header records which decisions were superseded by the extraction (where it lives, what starts it, `bootstrap.py`), and it carries the observability section added after the 16-day no-op. |
| `2026-07-14-plan-1-python-core.md` | Execution plan for the Python core — TDD task list with the code as it was first written. |
| `2026-07-14-plan-2-bct-integration.md` | Execution plan for the BCT integration that this repo exists to undo: `SkillLoopDeploy.swift`, the bundle payload folder-ref, and the global-idle curator trigger. |
| `worklog-excerpt-bomi-terminal.md` | All 16 tagged worklog entries from that period, verbatim. |
| `task-*.md` | The five devmode task snapshots: `hermes-bct` (build), `curator-age-floor`, `curator-key-fix` (the no-op), `curator-observ` (the run log), `hermes-plugin` (this extraction). |

## Why the git history is here too

`git log` and `git blame` in this repo reach back to 2026-07-14: the pre-extraction
commits were imported with `git filter-repo --subdirectory-filter .claude/skill-loop`
and grafted beneath the first standalone commit. That matters more here than in most
repos — the load-bearing thing about this code is *why* a line exists, and several
lines exist because of a specific failure:

- the reentrancy sentinel, because `claude -p` fires its own `SessionEnd`
- the age floor, because `count == 0` cannot distinguish stale from newborn
- the two-stage learn, because a later lesson used to fork a stale twin
- everything in `runlog.py`, because the curator applied nothing for 16 days and no
  artifact could have revealed it

Blame that stops at the extraction would have hidden all of it.

Commits before the graft point still show the old paths in their messages
(`.claude/skill-loop/...`) and one commit references BCT's Swift deployer. That is
accurate history, not an error.
