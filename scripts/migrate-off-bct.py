#!/usr/bin/env python3
"""One-time migration off the BCT-embedded skill loop.

Before this plugin existed, the loop was deployed by the BCT terminal app: it
copied a payload into ~/.claude/scripts/skill-loop/ on every launch and merged two
hook entries into ~/.claude/settings.json pointing at absolute paths there. This
plugin's hooks/hooks.json now owns those hooks, so the old wiring must go or BOTH
copies fire and every session end learns twice.

Idempotent: run it as often as you like. Reports what it did and exits 0 unless it
genuinely could not write.

ORDER MATTERS. Deploy a BCT build with SkillLoopDeploy REMOVED before running this.
The old SkillLoopDeploy.deploy() overwrites ~/.claude/scripts/skill-loop
unconditionally at launch and re-runs its bootstrap, so a stale BCT.app will
happily undo everything below the next time it starts.

    python3 migrate-off-bct.py --dry-run   # show what would change
    python3 migrate-off-bct.py             # do it
"""
from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path

# The two hook commands BCT's bootstrap.py merged in. Matched by substring rather
# than equality: the path was absolute and user-specific ("/Users/<you>/.claude/
# scripts/skill-loop/learn.py"), and older deployments quoted it differently.
LEGACY_MARKERS = ("scripts/skill-loop/learn.py", "scripts/skill-loop/usage.py")

LEGACY_PAYLOAD = Path.home() / ".claude" / "scripts" / "skill-loop"
SETTINGS = Path.home() / ".claude" / "settings.json"


def _entry_is_legacy(entry: dict) -> bool:
    for h in (entry.get("hooks") or []):
        cmd = h.get("command") or ""
        if any(m in cmd for m in LEGACY_MARKERS):
            return True
    return False


def strip_legacy_hooks(settings: dict):
    """Remove only the entries that point at the old payload. Returns
    (new_settings, removed_commands) and never touches anything else."""
    settings = json.loads(json.dumps(settings))     # deep copy, no mutation
    hooks = settings.get("hooks")
    removed = []
    if not isinstance(hooks, dict):
        return settings, removed
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        keep = []
        for entry in entries:
            if isinstance(entry, dict) and _entry_is_legacy(entry):
                for h in (entry.get("hooks") or []):
                    removed.append("%s: %s" % (event, h.get("command")))
            else:
                keep.append(entry)
        if keep:
            hooks[event] = keep
        else:
            del hooks[event]                        # don't leave an empty array
    if not hooks:
        del settings["hooks"]
    return settings, removed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Remove the BCT-era skill-loop wiring.")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="print what would change and touch nothing")
    ap.add_argument("--settings", default=str(SETTINGS))
    ap.add_argument("--payload", default=str(LEGACY_PAYLOAD))
    args = ap.parse_args(argv)

    settings_path, payload = Path(args.settings), Path(args.payload)
    plan, did = [], []

    try:
        current = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = None

    if current is None:
        plan.append("settings: %s unreadable or absent — nothing to strip" % settings_path)
        new_settings, removed = None, []
    else:
        new_settings, removed = strip_legacy_hooks(current)
        if removed:
            for cmd in removed:
                plan.append("settings: remove hook  %s" % cmd)
        else:
            plan.append("settings: no legacy skill-loop hooks found (already clean)")

    if payload.is_dir():
        plan.append("payload: remove %s" % payload)
    else:
        plan.append("payload: %s absent (already clean)" % payload)

    print("Plan:" if args.dry_run else "Migrating:")
    for line in plan:
        print("  -", line)

    if args.dry_run:
        print("\nDry run — nothing changed.")
        return 0

    if removed and new_settings is not None:
        backup = settings_path.with_suffix(".json.pre-hermes-migrate")
        try:
            shutil.copy2(settings_path, backup)
            settings_path.write_text(json.dumps(new_settings, indent=2) + "\n",
                                     encoding="utf-8")
            did.append("stripped %d hook(s); backup at %s" % (len(removed), backup))
        except OSError as e:
            print("FAILED to rewrite %s: %s" % (settings_path, e), file=sys.stderr)
            return 1

    if payload.is_dir():
        try:
            shutil.rmtree(payload)
            did.append("removed %s" % payload)
        except OSError as e:
            print("FAILED to remove %s: %s" % (payload, e), file=sys.stderr)
            return 1

    print("\nDone." if did else "\nNothing to do.")
    for line in did:
        print("  -", line)
    if did:
        print("\nYour learned skills in ~/.claude/skills/ and your config at")
        print("~/.claude/skill-loop.json were NOT touched — the plugin reads both.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
