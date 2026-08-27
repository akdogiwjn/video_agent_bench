#!/bin/bash
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# entrypoint.sh — launches OpenClaw with the task file.
#
# This script does ONLY infrastructure:
#   - configure OpenClaw (openclaw.json, exec-approvals.json, workspace)
#   - read the task file path from $1
#   - invoke openclaw agent with the configured model and timeout
#   - export trajectory after agent completes (even on failure)
#
# It must NOT contain any GEN/EDIT business logic. The agent decides
# what tools to call, what order to call them, and how to produce the
# final artifact. Runner post-task repair is forbidden.
# ---------------------------------------------------------------------------

TASK_FILE="${1:?Usage: entrypoint.sh <task_file>}"
AGENT_MODEL="${AGENT_MODEL:?AGENT_MODEL must be set}"
TIMEOUT="${TIMEOUT:-3600}"
SESSION_KEY="${SESSION_KEY:-bench-$(date +%s)}"

if [ ! -f "$TASK_FILE" ]; then
    echo "ERROR: task file not found: $TASK_FILE" >&2
    exit 1
fi

TASK_MESSAGE="$(cat "$TASK_FILE")"

# --- Configure OpenClaw before launch ---
OPENCLAW_HOME="/root/.openclaw"
mkdir -p "$OPENCLAW_HOME"

# openclaw.json — skill loader + environment + workspace
cat > "$OPENCLAW_HOME/openclaw.json" <<OCJSON
{
  "skills": {
    "load": {
      "extraDirs": ["/workspace/skills"],
      "watch": true,
      "watchDebounceMs": 250
    }
  },
  "env": {
    "shellEnv": {
      "enabled": false,
      "timeoutMs": 15000
    },
    "vars": {},
    "OUTPUT_DIR": "/workspace/output"
  },
  "agents": {
    "defaults": {
      "workspace": "/workspace",
      "timeoutSeconds": ${TIMEOUT},
      "verboseDefault": "full",
      "maxConcurrent": 100,
      "subagents": {
        "maxConcurrent": 100
      }
    },
    "list": [
      {
        "id": "main"
      }
    ]
  }
}
OCJSON

# exec-approvals.json — current OpenClaw schema
cat > "$OPENCLAW_HOME/exec-approvals.json" <<'EAJSON'
{
  "version": 1,
  "defaults": {
    "security": "full",
    "ask": "off",
    "askFallback": "full"
  }
}
EAJSON

export OUTPUT_DIR="/workspace/output"
export OPENCLAW_WORKSPACE_DIR="/workspace"

echo "=== video-agent-bench entrypoint ==="
echo "  task_file:    $TASK_FILE"
echo "  model:        $AGENT_MODEL"
echo "  timeout:      $TIMEOUT"
echo "  session_key:  $SESSION_KEY"
echo "  workspace:    /workspace"
echo "==================================="

# --- Run agent ---
# Use set +e so that agent failure does NOT prevent trajectory export.
# Trajectory is most critical when the agent fails or times out.
set +e
openclaw agent \
    --local \
    --agent main \
    --model "$AGENT_MODEL" \
    --session-key "$SESSION_KEY" \
    --timeout "$TIMEOUT" \
    --message "$TASK_MESSAGE"
AGENT_EXIT_CODE=$?
set -e

echo "  agent exit code: $AGENT_EXIT_CODE"

# --- Export trajectory (runs even if agent failed) ---
echo "=== Exporting trajectory (session_key=$SESSION_KEY) ==="
mkdir -p /workspace/logs

set +e
openclaw sessions export-trajectory \
    --session-key "$SESSION_KEY" \
    --workspace /workspace \
    --output benchmark-trajectory \
    --json > /workspace/logs/trajectory_export.log 2>&1
EXPORT_EXIT_CODE=$?
set -e

if [ $EXPORT_EXIT_CODE -ne 0 ]; then
    echo "WARNING: trajectory export failed (exit=$EXPORT_EXIT_CODE)" >&2
    echo "  Log:" >&2
    cat /workspace/logs/trajectory_export.log >&2 || true
fi

# The export lands in <workspace>/.openclaw/trajectory-exports/<output>/
# NOT in /root/.openclaw/ (the --workspace flag controls the export location)
EXPORT_DIR="/workspace/.openclaw/trajectory-exports/benchmark-trajectory"
if [ -d "$EXPORT_DIR" ]; then
    mkdir -p /workspace/logs/trajectory_bundle
    cp -a "$EXPORT_DIR"/. /workspace/logs/trajectory_bundle/ 2>/dev/null || true
    echo "  Trajectory bundle copied to /workspace/logs/trajectory_bundle/"
else
    echo "WARNING: export directory not found at $EXPORT_DIR" >&2
    # Fallback: check /root/.openclaw/ in case of older OpenClaw versions
    FALLBACK_DIR="$OPENCLAW_HOME/trajectory-exports/benchmark-trajectory"
    if [ -d "$FALLBACK_DIR" ]; then
        mkdir -p /workspace/logs/trajectory_bundle
        cp -a "$FALLBACK_DIR"/. /workspace/logs/trajectory_bundle/ 2>/dev/null || true
        echo "  Trajectory bundle found at fallback location"
    fi
fi

# Copy SQLite database for raw state preservation
SQLITE_DB="$OPENCLAW_HOME/agents/main/agent/openclaw-agent.sqlite"
if [ -f "$SQLITE_DB" ]; then
    cp "$SQLITE_DB" /workspace/logs/openclaw-agent.sqlite 2>/dev/null || true
fi

exit "$AGENT_EXIT_CODE"
