#!/bin/bash
# postToolUse hook, matched on Shell: once per conversation, after the agent
# runs its first review/diff-reading command, remind it to use the
# `code-review` skill instead of an ad hoc read. See CODING_STANDARDS.md for
# what CI already enforces (so the Standards axis of that skill knows what to
# skip). Never blocks anything: observe-only, best-effort.
set -euo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
conversation_id=$(printf '%s' "$input" | jq -r '.conversation_id // "unknown"' 2>/dev/null || true)

if [[ -z "$command" ]]; then
  echo '{}'
  exit 0
fi

# Tight, deliberately narrow: first look at a PR/branch diff, not every git/gh call.
if ! [[ "$command" =~ gh[[:space:]]+pr[[:space:]]+diff ]] \
  && ! [[ "$command" =~ gh[[:space:]]+pr[[:space:]]+view.*--?-?diff ]] \
  && ! [[ "$command" =~ git[[:space:]]+diff.*(develop|main|origin|HEAD~|merge-base) ]]; then
  echo '{}'
  exit 0
fi

state_dir="$(dirname "$0")/.state"
mkdir -p "$state_dir"
marker="$state_dir/$conversation_id.reminded"
if [[ -e "$marker" ]]; then
  echo '{}'
  exit 0
fi
: > "$marker"

cat <<'EOF'
{"additional_context": "This repo expects a branch/PR/diff review to go through the `code-review` skill (two-axis Standards + Spec, run as parallel sub-agents) rather than an ad hoc read. `CODING_STANDARDS.md` at the repo root lists exactly what CI already enforces, so the Standards axis should skip those and focus on judgement calls. If this task is a review, use the skill now."}
EOF
