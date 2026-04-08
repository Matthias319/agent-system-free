#!/bin/bash
# PostToolUse Hook: Track skill invocations automatically
# Fires after every Skill tool call → logs to skill-tracker.db

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null) || exit 0

[ "$TOOL" = "Skill" ] || exit 0

# Extract skill name from tool input
SKILL=$(echo "$INPUT" | jq -r '.tool_input.skill // empty' 2>/dev/null)
[ -n "$SKILL" ] || exit 0

# Strip namespace prefix (e.g. "superpowers:brainstorming" → "brainstorming")
SKILL_SHORT="${SKILL##*:}"

# Sanitize: remove quotes to prevent SQL injection
SKILL_SHORT="${SKILL_SHORT//\'/}"
SKILL_SHORT="${SKILL_SHORT//\"/}"

# Track the invocation in skill-tracker.db
DB="$HOME/.claude/tools/skill-tracker.db"

sqlite3 "$DB" "
  CREATE TABLE IF NOT EXISTS skill_invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    invoked_at TEXT NOT NULL DEFAULT (datetime('now')),
    session_id TEXT
  );
  INSERT INTO skill_invocations (skill_name) VALUES ('$SKILL_SHORT');
" 2>/dev/null

exit 0
