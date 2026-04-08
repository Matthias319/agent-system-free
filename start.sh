#!/bin/bash
# Start OpenCode with env vars loaded from .env
set -a
source "$(dirname "$0")/.env" 2>/dev/null
set +a
exec opencode "$@"
