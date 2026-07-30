<!-- scripts/prompts/consolidate.md -->
You are merging two overlapping skills from a personal skill collection into one.
You are given the SURVIVING skill and the skill BEING FOLDED IN, each as a full
`SKILL.md` (frontmatter + body).

Return the survivor's new **body**. The frontmatter is handled for you — do not
write one, and do not include the `---` fences.

What matters:

- **Lose nothing.** Anything the folded-in skill knows that the survivor does not
  must appear in your output. Specific commands, exact error strings, file paths,
  version numbers, gotchas and their reasons — these are the whole value. If you
  cannot fit a detail gracefully, add it as its own short section rather than
  dropping it.
- **Do not merely concatenate.** Where both describe the same step, write it once,
  keeping the clearer wording and the more precise details from either side.
- **Keep the survivor's shape.** Its section order and heading style are the frame;
  fold the other's material into that structure.
- **Preserve contradictions explicitly.** If the two disagree about what works,
  say so and note the conditions under which each held, rather than silently
  picking one. A later lesson correcting an earlier one should read as a
  correction, with the superseded approach and why it failed.
- Keep it as tight as accuracy allows. This body is injected into future sessions.

Reply with ONE JSON object and nothing else:

```
{"body": "<the merged markdown body>"}
```

If the two skills genuinely do not overlap enough to merge — different problems
that happen to share vocabulary — reply `{"body": ""}`. Both skills are then kept
as they are, which is the right outcome; a bad merge is worse than two skills.
