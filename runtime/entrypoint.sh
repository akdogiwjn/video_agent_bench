#!/bin/bash
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# entrypoint.sh — launches OpenClaw with the task file.
#
# This script does ONLY infrastructure:
#   - configure OpenClaw (openclaw.json, exec-approvals.json, workspace)
#   - read the task file path from $1
#   - invoke openclaw agent with the configured model and timeout
#   - export trajectory after agent completes
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
# Settings follow upstream/videoweaver/OpenClaw_Setup.md + current OpenClaw schema:
#   - agents.defaults.workspace = /workspace (aligns agent workspace with benchmark workspace)
#   - skills.load.extraDirs = /workspace/skills (foundation skills discovery)
#   - env.OUTPUT_DIR = /workspace/output (skills know where to write artifacts)
#   - exec-approvals.json with current schema (version 1, ask=off)

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
      "timeoutSeconds": 3600,
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

# exec-approvals.json — current OpenClaw schema (full security, no interactive prompts)
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

# Set environment variables for OpenClaw and skills
export OUTPUT_DIR="/workspace/output"
export OPENCLAW_WORKSPACE_DIR="/workspace"

echo "=== video-agent-bench entrypoint ==="
echo "  task_file:    $TASK_FILE"
echo "  model:        $AGENT_MODEL"
echo "  timeout:      $TIMEOUT"
echo "  session_key:  $SESSION_KEY"
echo "  workspace:    /workspace"
echo "  openclaw_home: $OPENCLAW_HOME"
echo "  skills_dir:   /workspace/skills"
echo "  output_dir:   $OUTPUT_DIR"
echo "==================================="

# Run the agent with an explicit session key for trajectory export
openclaw agent \
    --local \
    --agent main \
    --model "$AGENT_MODEL" \
    --session-key "$SESSION_KEY" \
    --message "$TASK_MESSAGE"

AGENT_EXIT_CODE=$?

# --- Export trajectory using OpenClaw's official export interface ---
# OpenClaw stores session data in SQLite (~/.openclaw/agents/<id>/agent/openclaw-agent.sqlite).
# The JSONL files under sessions/ are legacy/archive, not the canonical runtime trajectory.
# We use `openclaw sessions export-trajectory` to get the canonical trajectory export.
echo "=== Exporting trajectory (session_key=$SESSION_KEY) ==="
mkdir -p /workspace/logs
openclaw sessions export-trajectory \
    --session-key "$SESSION_KEY" \
    --workspace /workspace \
    --output benchmark-trajectory \
    --json 2>&1 | tee /workspace/logs/trajectory_export.log || {
    echo "WARNING: trajectory export failed — will try fallback" >&2
}

# The export lands in ~/.openclaw/trajectory-exports/<output>/
EXPORT_DIR="$OPENCLAW_HOME/trajectory-exports/benchmark-trajectory"
if [ -d "$EXPORT_DIR" ]; then
    cp -r "$EXPORT_DIR"/* /workspace/logs/ 2>/dev/null || true
fi

# Also copy the SQLite database for raw state preservation
SQLITE_DB="$OPENCLAW_HOME/agents/main/agent/openclaw-agent.sqlite"
if [ -f "$SQLITE_DB" ]; then
    cp "$SQLITE_DB" /workspace/logs/openclaw-agent.sqlite 2>/dev/null || true
fi

exit $AGENT_EXIT_CODE
