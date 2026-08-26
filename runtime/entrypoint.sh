#!/bin/bash
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# entrypoint.sh — launches OpenClaw with the task file.
#
# This script does ONLY infrastructure:
#   - read the task file path from $1
#   - invoke openclaw agent with the configured model and timeout
#
# It must NOT contain any GEN/EDIT business logic. The agent decides
# what tools to call, what order to call them, and how to produce the
# final artifact. Runner post-task repair is forbidden.
# ---------------------------------------------------------------------------

TASK_FILE="${1:?Usage: entrypoint.sh <task_file>}"
AGENT_MODEL="${AGENT_MODEL:?AGENT_MODEL must be set}"
TIMEOUT="${TIMEOUT:-3600}"

if [ ! -f "$TASK_FILE" ]; then
    echo "ERROR: task file not found: $TASK_FILE" >&2
    exit 1
fi

TASK_MESSAGE="$(cat "$TASK_FILE")"

echo "=== video-agent-bench entrypoint ==="
echo "  task_file: $TASK_FILE"
echo "  model:     $AGENT_MODEL"
echo "  timeout:   $TIMEOUT"
echo "  workspace: $(pwd)"
echo "==================================="

openclaw agent \
    --local \
    --agent main \
    --model "$AGENT_MODEL" \
    --timeout "$TIMEOUT" \
    --message "$TASK_MESSAGE"
