#!/usr/bin/env python3
# scripts/doctor.py
"""Self-check for the hermes skill loop.

This exists because of a specific failure: the curator applied nothing for 16 days
(2026-07-14 to 07-30) and every artifact still looked healthy — `.curator_state`
stamped `last_run` on every run, so "it ran" and "it worked" were indistinguishable.
The run log fixed the record-keeping; `doctor` is the thing that reads that record
and tells you when it does not add up, without you having to know what to look for.

The single most valuable check here is `reconciliation`: for a healthy curator run
`proposed == kept + len(applied) + len(skipped)`. The 16-day defect produced runs
where the model proposed a dozen actions and every one of them evaporated. That is
arithmetic, not judgement — one check would have caught it on day one.

Pure functions returning {name, status, detail}; `main()` only gathers, calls and
renders. Exit 1 if anything FAILs, so it is usable from CI or a wrapper script.
"""
from __future__ import annotations
import json, os, re, shutil, sys
from pathlib import Path

import runlog
import skill_meta

OK, WARN, FAIL = "ok", "warn", "fail"

MIN_PYTHON = (3, 9)

# Model generations that were current when this loop was built and are now behind.
# Not an error -- a retired id still resolves until it doesn't, and when it stops
# resolving the loop can only RECORD the failure, never repair it. Naming the risk
# early is cheaper than reading it out of an `error` outcome later.
AGEING_MODEL_PREFIXES = ("claude-opus-4", "claude-sonnet-4", "claude-haiku-3",
                         "claude-3", "claude-2")

# learn.py caps a slug at this many characters. A name landing exactly on the cap
# was almost certainly cut mid-word.
SLUG_CAP = 40


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


# --- environment -------------------------------------------------------------

def check_python(version_info=None) -> dict:
    v = tuple(version_info or sys.version_info[:3])
    text = ".".join(str(p) for p in v)
    if v[:2] < MIN_PYTHON:
        return _check("python", FAIL,
                      "%s is below the required %s — the hooks run under whatever "
                      "python3 resolves to, so this is fatal"
                      % (text, ".".join(map(str, MIN_PYTHON))))
    return _check("python", OK, text)


def check_claude_cli(which=None) -> dict:
    which = which or shutil.which
    path = which("claude")
    if not path:
        return _check("claude-cli", FAIL,
                      "`claude` is not on PATH — learn and curate cannot run at all. "
                      "This presents in the log as an `error` outcome, forever.")
    return _check("claude-cli", OK, str(path))


def check_config(config: dict) -> dict:
    cfg = config or {}
    learn = cfg.get("learn_model") or cfg.get("model") or "claude-sonnet-5"
    curator = cfg.get("curator_model") or cfg.get("model") or "claude-sonnet-5"
    detail = "learn=%s curator=%s" % (learn, curator)
    if cfg.get("enabled") is False:
        return _check("config", WARN, "enabled: false — the loop is switched off. " + detail)
    ageing = [m for m in (learn, curator)
              if any(m.startswith(p) for p in AGEING_MODEL_PREFIXES)]
    if ageing:
        return _check("config", WARN,
                      "%s — %s is an older model generation; when an id is retired "
                      "`claude -p` fails and the loop can only record it"
                      % (detail, ", ".join(sorted(set(ageing)))))
    return _check("config", OK, detail)


def check_log_writable(log_path) -> dict:
    p = Path(log_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8"):
            pass
        return _check("log", OK, str(p))
    except Exception as e:
        return _check("log", FAIL,
                      "cannot write %s (%s: %s) — every diagnostic below goes blind"
                      % (p, type(e).__name__, e))


# --- evidence from the log ---------------------------------------------------

def check_hooks_firing(events: list) -> dict:
    """There is no way to introspect Claude Code's active hook table, so use the
    log as evidence instead: a `learn` or `usage` event can only exist because a
    hook fired. A curator event does not count — that can be a manual run."""
    hook_roles = [e for e in (events or []) if e.get("role") in ("learn", "usage")]
    if not hook_roles:
        return _check("hooks", WARN,
                      "no learn/usage events logged yet — either the plugin is not "
                      "installed, or no session has ended since it was. End a "
                      "session and re-run.")
    last = hook_roles[-1]
    return _check("hooks", OK,
                  "%d hook event(s); last %s at %s"
                  % (len(hook_roles), last.get("role"), last.get("ts")))


def _last_curator(events: list):
    runs = [e for e in (events or []) if e.get("role") == "curator"]
    return runs[-1] if runs else None


def check_last_curator_run(events: list) -> dict:
    run = _last_curator(events)
    if run is None:
        return _check("last-run", WARN, "the curator has never run")
    outcome = run.get("outcome")
    when = run.get("ts")
    if outcome == "error":
        return _check("last-run", FAIL,
                      "last run errored at %s: %s" % (when, run.get("error")))
    if outcome == "unparseable":
        return _check("last-run", FAIL,
                      "last run at %s could not parse the model's reply: %r"
                      % (when, (run.get("raw_head") or "")[:80]))
    return _check("last-run", OK,
                  "%s at %s (applied=%s skipped=%d)"
                  % (outcome, when, run.get("applied"), len(run.get("skipped") or [])))


def check_reconciliation(events: list) -> dict:
    """proposed == kept + applied + skipped, or actions are being dropped."""
    run = _last_curator(events)
    if run is None or run.get("outcome") not in ("applied", "dry_run"):
        return _check("reconciliation", WARN, "no completed run to reconcile")
    proposed = int(run.get("proposed") or 0)
    kept = int(run.get("kept") or 0)
    acted = len(run.get("applied") or []) + len(run.get("would_apply") or [])
    skipped = len(run.get("skipped") or [])
    total = kept + acted + skipped
    if proposed != total:
        return _check("reconciliation", FAIL,
                      "%d proposed but only %d accounted for (kept=%d acted=%d "
                      "skipped=%d) — %d action(s) went nowhere. This is the exact "
                      "signature of the 2026-07 no-op."
                      % (proposed, total, kept, acted, skipped, proposed - total))
    return _check("reconciliation", OK,
                  "%d proposed = %d kept + %d acted + %d skipped"
                  % (proposed, kept, acted, skipped))


# --- the skill store ---------------------------------------------------------

def _learned(skills_dir):
    return skill_meta.list_learned(Path(skills_dir))


def _description(md) -> str:
    fm = skill_meta.read_frontmatter(md) or {}
    return fm.get("description", "") or ""


def check_skills(skills_dir, usage: dict) -> dict:
    usage = usage or {}
    mds = _learned(skills_dir)
    if not mds:
        return _check("skills", WARN, "no learned skills yet")
    listing_chars = 0
    never = 0
    for md in mds:
        slug = md.parent.name
        listing_chars += len(slug) + 2 + len(_description(md))
        if int((usage.get(slug) or {}).get("count", 0)) == 0:
            never += 1
    tokens = listing_chars // 4          # rough, but the ratio is what matters
    detail = ("learned=%d never-used=%d listing~%d tok"
              % (len(mds), never, tokens))
    # Every learned skill's description is injected into EVERY session, so unused
    # ones are a standing cost. A majority never used means curation is not
    # happening -- which is what a broken curator looks like from the outside.
    if len(mds) >= 4 and never * 2 > len(mds):
        return _check("skills", WARN,
                      detail + " — most learned skills have never been used; "
                      "run `curator.py --dry-run` to see what it would retire")
    return _check("skills", OK, detail)


def check_truncated_slugs(skills_dir) -> dict:
    hits = [md.parent.name for md in _learned(skills_dir)
            if len(md.parent.name) >= SLUG_CAP]
    if not hits:
        return _check("slugs", OK, "no slugs at the %d-char cap" % SLUG_CAP)
    return _check("slugs", WARN,
                  "%d slug(s) sit exactly on the %d-char cap and were likely cut "
                  "mid-word, which hurts matching: %s"
                  % (len(hits), SLUG_CAP, ", ".join(sorted(hits)[:5])))


def check_descriptions(skills_dir) -> dict:
    blank = [md.parent.name for md in _learned(skills_dir) if not _description(md).strip()]
    if not blank:
        return _check("descriptions", OK, "every learned skill has a description")
    return _check("descriptions", FAIL,
                  "%d skill(s) have no description and can therefore never be "
                  "matched, while still costing a listing line: %s"
                  % (len(blank), ", ".join(sorted(blank))))


# --- assembly ----------------------------------------------------------------

def run_checks(*, skills_dir, usage, config, events, log_path,
               version_info=None, which=None) -> list:
    return [
        check_python(version_info),
        check_claude_cli(which),
        check_config(config),
        check_log_writable(log_path),
        check_hooks_firing(events),
        check_last_curator_run(events),
        check_reconciliation(events),
        check_skills(skills_dir, usage),
        check_truncated_slugs(skills_dir),
        check_descriptions(skills_dir),
    ]


_LABEL = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}


def render(checks: list) -> str:
    lines = []
    for c in checks:
        lines.append("%s  %-15s %s" % (_LABEL.get(c["status"], "?   "),
                                       c["name"], c["detail"]))
    fails = sum(1 for c in checks if c["status"] == FAIL)
    warns = sum(1 for c in checks if c["status"] == WARN)
    lines.append("")
    lines.append("%d ok, %d warn, %d fail"
                 % (len(checks) - fails - warns, warns, fails))
    return "\n".join(lines)


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gather() -> dict:
    home = Path.home() / ".claude"
    skills = home / "skills"
    return dict(
        skills_dir=skills,
        usage=_load_json(skills / ".usage.json"),
        config=_load_json(home / "skill-loop.json"),
        events=runlog.read_events(),
        log_path=runlog.log_path(),
        version_info=sys.version_info[:3],
        which=shutil.which,
    )


def main(argv=None) -> int:
    checks = run_checks(**_gather())
    print(render(checks))
    return 1 if any(c["status"] == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
