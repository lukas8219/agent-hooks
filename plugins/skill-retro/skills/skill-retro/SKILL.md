---
name: skill-retro
description: At the end of a task, offer to capture a reusable workflow, lesson, or domain procedure as an agent skill, and choose the appropriate repository.
---

# Skill retro

At the end of a task, look for a reusable method or domain lesson that would help in future sessions. Routine one-off edits do not need a skill.

If there is a clear candidate, briefly tell the user what the skill would capture and ask whether they want it created. Do not generate or save a skill before they agree. If there is no clear candidate, finish without mentioning this check.

## Choose the destination

- Put a skill that captures conventions or workflows specific to the current project in that project's `.agents/skills/<skill-name>/`.
- Put a generally useful skill in the repository named by `SKILL_MARKETPLACE_REPO` (defaults to `marketplace`), under its `.agents/skills/<skill-name>/`.
- Check that the marketplace repository is actually available and writable before using it. If it is unavailable, ask before falling back to the current project repository.

## Generate an approved skill

Prefer Hugging Face `upskill` when it is installed and a usable transcript or trace file is available:

```sh
upskill generate "<reusable task the skill teaches>" --from "<trace-file>" --output "<chosen-repository>/.agents/skills/<skill-name>"
```

The Hugging Face CLI takes a task description and a trace file; it does not expose a `--from-session` option. Do not invent a trace path. If no usable trace is available, ask the user for one or offer to draft the skill directly from the completed work after their approval.

Keep the instructions focused on repeatable steps, decisions, and pitfalls, and avoid including secrets or unrelated conversation details.
