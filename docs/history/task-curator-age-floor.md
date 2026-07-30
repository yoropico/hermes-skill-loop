## curator-age-floor — DONE (landed)
- PR #213 merged to master (3c441ab). Follow-up of the hermes-bct task (item #2).
- Curator now gets a per-skill age_days signal + a curator_min_age_days=7 code floor that vetoes
  archiving any skill younger than the floor (deterministic firewall, not just prompt).
- 6 new tests, 53/53 skill-loop green, py_compile 3.9 OK. Also live-patched ~/.claude/scripts/skill-loop.
- DEPLOY: repo=master(done) + ~/.claude live-patch(done); BCT bundle carry pending next app rebuild.
