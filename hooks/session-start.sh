#!/bin/bash
# SessionStart Hook — Inject startup context into new sessions
# Injects: active lessons, compact-state recovery (if recent), git status hint

OUTPUT=""

# 1. Inject active lessons (if any exist)
LESSONS=$("$HOME/.claude/tools/lessons.py" inject 2>/dev/null)
if [ -n "$LESSONS" ]; then
  OUTPUT="${OUTPUT}${LESSONS}\n\n"
fi

# 2. Check for recent compact-state (last 30 minutes = context recovery)
COMPACT_STATE="$HOME/.claude/data/compact-state.yaml"
if [ -f "$COMPACT_STATE" ]; then
  AGE_SECONDS=$(( $(date +%s) - $(stat -c %Y "$COMPACT_STATE" 2>/dev/null || echo 0) ))
  if [ "$AGE_SECONDS" -lt 1800 ]; then
    OUTPUT="${OUTPUT}# Context Recovery (compact-state from ${AGE_SECONDS}s ago)\n"
    OUTPUT="${OUTPUT}A recent context compaction occurred. Read ${COMPACT_STATE} to recover state.\n\n"
  fi
fi

# 3. Output if anything was collected
if [ -n "$OUTPUT" ]; then
  echo -e "$OUTPUT" >&2
fi
