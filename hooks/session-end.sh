#!/bin/bash
# Stop Hook (Session End) - Persist learnings when session ends
# Raspberry Pi / Linux version

SESSIONS_DIR="${HOME}/.claude/sessions"
TODAY=$(date '+%Y-%m-%d')
SESSION_FILE="${SESSIONS_DIR}/${TODAY}-session.md"

mkdir -p "$SESSIONS_DIR"

# If session file exists for today, update the end time
if [ -f "$SESSION_FILE" ]; then
  # Update Last Updated timestamp (Linux compatible)
  sed -i "s/\*\*Last Updated:\*\*.*/\*\*Last Updated:\*\* $(date '+%H:%M')/" "$SESSION_FILE" 2>/dev/null
  echo "[Memory] Updated session file: $SESSION_FILE" >&2
else
  # Create new session file with template
  cat > "$SESSION_FILE" << EOF
# Session: $TODAY
**Date:** $TODAY
**Started:** $(date '+%H:%M')
**Last Updated:** $(date '+%H:%M')

---

## Current State

[Session context goes here - Claude should update this]

### Completed
- [ ]

### In Progress
- [ ]

### Notes for Next Session
-

### Context to Load
\`\`\`
[relevant files]
\`\`\`
EOF
  echo "[Memory] Created session file: $SESSION_FILE" >&2
fi

# Zettelkasten: MEMORY.md aktualisieren (Backup-Trigger)
~/.claude/hooks/zettel-hooks.sh session-end
