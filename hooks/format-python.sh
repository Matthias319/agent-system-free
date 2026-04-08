#!/bin/bash
# PostToolUse Hook: Auto-format Python files with ruff
# Reads JSON from stdin (not environment variables!)

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0

# Only process .py files
if [[ "$FILE_PATH" == *.py ]] && [[ -f "$FILE_PATH" ]]; then
    cd "$(dirname "$FILE_PATH")" 2>/dev/null || exit 0
    ~/.local/bin/ruff check --fix "$FILE_PATH" 2>/dev/null
    ~/.local/bin/ruff format "$FILE_PATH" 2>/dev/null
    echo "[Hook] Python formatted: $(basename "$FILE_PATH")" >&2
fi

exit 0
