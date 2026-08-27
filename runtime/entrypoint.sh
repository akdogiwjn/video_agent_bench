#!/bin/bash
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# entrypoint.sh — launches OpenClaw with the task file.
#
# This script does ONLY infrastructure:
#   - configure OpenClaw (openclaw.json, exec-approvals.json, workspace)
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

# --- Configure OpenClaw before launch ---
# These settings follow upstream/videoweaver/OpenClaw_Setup.md:
#   - skills.load.extraDirs points to /workspace/skills so OpenClaw discovers
#     foundation skills mounted by the runner.
#   - env.OUTPUT_DIR so skills know where to write artifacts.
#   - exec-approvals.json defaults.security = "full" so the agent can
#     execute tools without interactive approval prompts.

OPENCLAW_HOME="/root/.openclaw"
mkdir -p "$OPENCLAW_HOME"

# openclaw.json — skill loader + environment
cat > "$OPENCLAW_HOME/openclaw.json" <<'OCJSON'
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

# exec-approvals.json — full security (no interactive prompts)
cat > "$OPENCLAW_HOME/exec-approvals.json" <<'EAJSON'
{
  "defaults": {
    "security": "full"
  }
}
EAJSON

# Set OUTPUT_DIR in the process environment as well (skills read it via os.environ)
export OUTPUT_DIR="/workspace/output"

echo "=== video-agent-bench entrypoint ==="
echo "  task_file: $TASK_FILE"
echo "  model:     $AGENT_MODEL"
echo "  timeout:   $TIMEOUT"
echo "  workspace: $(pwd)"
echo "  openclaw config: $OPENCLAW_HOME/openclaw.json"
echo "  skills dir: /workspace/skills"
echo "  output dir: $OUTPUT_DIR"
echo "==================================="

openclaw agent \
    --local \
    --agent main \
    --model "$AGENT_MODEL" \
    --timeout "$TIMEOUT" \
    --message "$TASK_MESSAGE"
