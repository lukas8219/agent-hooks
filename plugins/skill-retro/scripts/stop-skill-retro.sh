#!/usr/bin/env bash
# Once per completed turn, ask the agent to consider whether it found a
# reusable pattern worth turning into a skill. Stop hooks run again after the
# agent continues, so the active flag prevents a loop.
set -uo pipefail

payload=$(cat)
active=$(printf '%s' "$payload" | jq -r '.stop_hook_active // false' 2>/dev/null) || exit 0
[ "$active" = "true" ] && exit 0

marketplace_repo=${SKILL_MARKETPLACE_REPO:-marketplace}
jq -n --arg marketplace "$marketplace_repo" --arg reason 'Review the work from this turn. If it revealed a reusable workflow, lesson, or domain procedure that would help in future sessions, ask the user whether they would like a skill created from it. If there is no clear reusable insight, finish normally. Do not create a skill unless the user agrees. For an approved skill, use the skill-retro instructions. Decide where it belongs: keep a project-specific skill in this repository; put a broadly reusable skill in the configured marketplace repository if that repository is available and writable. If unavailable, explain that and place it in this repository only if the user agrees. Use Hugging Face upskill when a usable session trace is available.' '{decision:"block",reason:($reason + " Marketplace repository (SKILL_MARKETPLACE_REPO): " + $marketplace + ".")}'
