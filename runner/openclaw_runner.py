"""OpenClaw execution module for video_agent_bench runner.

Manages Docker container lifecycle, runs OpenClaw agent, and collects
trajectory artifacts. The runner does NOT contain any business logic —
it only manages infrastructure.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


def get_docker_image_id(image: str) -> str:
    """Get the Docker image ID (digest) for the specified image."""
    try:
        result = subprocess.run(
            ["docker", "images", "-q", "--no-trunc", image],
            capture_output=True, text=True, timeout=10,
        )
        image_id = result.stdout.strip()
        if image_id:
            return image_id
    except Exception:
        pass
    return "unknown"


def get_openclaw_version(image: str) -> str:
    """Get the OpenClaw version from the Docker image.

    Uses --entrypoint /bin/bash to bypass the agent image's ENTRYPOINT
    (which runs entrypoint.sh and would treat 'bash' as a task file).
    """
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/bin/bash",
             image, "-c", "openclaw --version"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def run_openclaw_in_docker(
    workspace: Path,
    task_file: str,
    image: str,
    agent_model: str,
    timeout: int = 3600,
    env_vars: dict[str, str] | None = None,
    openclaw_state_dir: Path | None = None,
    case_type: str = "gen",
) -> dict:
    """Run OpenClaw agent inside a Docker container.

    Mounts:
    - workspace → /workspace (task, materials, references, skills, output, logs)
    - openclaw_state_dir → /root/.openclaw (session data, trajectory, raw state)

    The openclaw_state_dir persists OpenClaw's internal state (sessions,
    trajectory, agent data) so it survives container shutdown.

    Returns a dict with:
        - exit_code: int
        - stdout: str
        - stderr: str
        - duration_seconds: float
    """
    workspace = Path(workspace).resolve()
    task_file_abs = str(workspace / task_file)

    # Docker mounts: workspace + OpenClaw state directory
    volumes = {str(workspace): {"bind": "/workspace", "mode": "rw"}}

    # Mount OpenClaw state directory to persist raw trajectory
    if openclaw_state_dir is None:
        openclaw_state_dir = workspace.parent / "openclaw_state"
    openclaw_state_dir = Path(openclaw_state_dir).resolve()
    openclaw_state_dir.mkdir(parents=True, exist_ok=True)
    volumes[str(openclaw_state_dir)] = {"bind": "/tmp/openclaw_home", "mode": "rw"}

    # Environment variables
    import uuid as _uuid
    session_key = f"bench-{_uuid.uuid4().hex[:8]}"
    env = {
        "AGENT_MODEL": agent_model,
        "TIMEOUT": str(timeout),
        "OUTPUT_DIR": "/workspace/output",
        "SESSION_KEY": session_key,
        "OPENCLAW_WORKSPACE_DIR": "/workspace",
        "CASE_TYPE": case_type,
    }
    if env_vars:
        env.update(env_vars)

    # Build docker run command
    # --rm ensures container is removed after exit (no leftover API keys)
    # UUID in name avoids collision on concurrent runs
    # --user ensures files created in mounted volumes are owned by host user
    import uuid as _uuid
    import os as _os
    host_uid = _os.getuid()
    host_gid = _os.getgid()
    container_name = f"video-agent-bench-{_uuid.uuid4().hex[:8]}"
    cmd = [
        "docker", "run", "--rm",
        "--user", f"{host_uid}:{host_gid}",
        "--name", container_name,
    ]
    for k, v in env.items():
        cmd.extend(["-e", f"{k}={v}"])
    for host_path, bind in volumes.items():
        cmd.extend(["-v", f"{host_path}:{bind['bind']}:{bind['mode']}"])
    cmd.extend([image, task_file])

    started = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 300,  # extra 5 min for container overhead
        )
    except subprocess.TimeoutExpired:
        # Container may still be running — force remove it
        subprocess.run(["docker", "rm", "-f", container_name],
                       capture_output=True, timeout=30)
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Agent timed out after {timeout}s",
            "duration_seconds": time.time() - started,
            "container_name": container_name,
        }
    duration = time.time() - started

    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_seconds": duration,
        "container_name": container_name,
    }


def collect_trajectory(workspace: Path, results_dir: Path, openclaw_state_dir: Path | None = None) -> dict:
    """Collect trajectory artifacts from the workspace and OpenClaw state.

    OpenClaw (current version) stores session data in SQLite:
        ~/.openclaw/agents/<id>/agent/openclaw-agent.sqlite

    The entrypoint.sh uses `openclaw sessions export-trajectory` to export
    the canonical trajectory to /workspace/logs/. We collect:
    1. Exported trajectory files (from workspace/logs/) → results/agent/
    2. Raw OpenClaw state including SQLite (from openclaw_state_dir) → results/agent/raw/
    3. Workspace logs (stdout, stderr, export log) → results/agent/
    4. Output files → results/output/
    5. Other artifacts → results/artifacts/
    """
    workspace = Path(workspace)
    results_dir = Path(results_dir)

    agent_dir = results_dir / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    raw_dir = agent_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    output_dir = results_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts_dir = results_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    collected = {
        "stdout_log": None,
        "stderr_log": None,
        "raw_openclaw_state": None,
        "trajectory_json": None,
        "tool_events_jsonl": None,
        "output_files": [],
        "artifact_files": [],
    }

    # 1. Copy raw OpenClaw state (SQLite DB, trajectory-exports, etc.)
    if openclaw_state_dir and openclaw_state_dir.is_dir():
        raw_dst = raw_dir
        for item in openclaw_state_dir.rglob("*"):
            if item.is_file() and item.name != ".DS_Store":
                try:
                    rel = item.relative_to(openclaw_state_dir)
                    dst = raw_dst / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dst)
                except (PermissionError, OSError):
                    pass  # Skip files we can't read (e.g. root-owned from Docker)
        collected["raw_openclaw_state"] = str(raw_dir)

        # Look for trajectory export files written by entrypoint.sh to workspace
        exports_dir = raw_dir / "trajectory-exports"
        if exports_dir.is_dir():
            events_file = exports_dir / "benchmark-trajectory" / "events.jsonl"
            if events_file.is_file() and collected["tool_events_jsonl"] is None:
                dst = agent_dir / "events.jsonl"
                shutil.copy2(events_file, dst)
                collected["tool_events_jsonl"] = str(dst)
                if collected["trajectory_json"] is None:
                    collected["trajectory_json"] = str(dst)

        # If trajectory export was incomplete (only high-level events),
        # use the full session JSONL which contains all message-level tool calls
        # Session JSONL files are in agents/main/sessions/*.jsonl (excluding *.trajectory.jsonl)
        session_jsonl_found = False
        for f in sorted(raw_dir.rglob("*.jsonl")):
            fname = f.name
            if "trajectory" in fname:
                # This is the export — already handled above
                continue
            # This is the full session JSONL with all events including tool calls
            dst = agent_dir / "trajectory.json"
            if not dst.exists():
                shutil.copy2(f, dst)
                collected["trajectory_json"] = str(dst)
                session_jsonl_found = True
                break

        # If no session JSONL found, try trajectory.jsonl as fallback
        if not session_jsonl_found and collected["trajectory_json"] is None:
            for f in raw_dir.rglob("*.trajectory.jsonl"):
                dst = agent_dir / "trajectory.json"
                if not dst.exists():
                    shutil.copy2(f, dst)
                    collected["trajectory_json"] = str(dst)
                    break

        # Fallback: look for any trajectory*.json in raw state
        if collected["trajectory_json"] is None:
            for f in raw_dir.rglob("trajectory*.json"):
                dst = agent_dir / f.name
                if not dst.exists():
                    shutil.copy2(f, dst)
                    if collected["trajectory_json"] is None:
                        collected["trajectory_json"] = str(dst)

        # Copy SQLite database for raw state preservation
        for f in raw_dir.rglob("*.sqlite"):
            dst = agent_dir / f.name
            if not dst.exists():
                shutil.copy2(f, dst)
                collected["artifact_files"].append(str(dst))

    # 2. Copy workspace logs (entrypoint.sh writes trajectory bundle here)
    logs_dir = workspace / "logs"
    if logs_dir.is_dir():
        # First: look for the trajectory bundle directory
        bundle_dir = logs_dir / "trajectory_bundle"
        if bundle_dir.is_dir():
            # Preserve the entire bundle as-is under raw/
            bundle_dst = raw_dir / "trajectory_bundle"
            if not bundle_dst.exists():
                shutil.copytree(bundle_dir, bundle_dst, dirs_exist_ok=True)

            # events.jsonl is the canonical event stream
            events_file = bundle_dir / "events.jsonl"
            if events_file.is_file():
                dst = agent_dir / "events.jsonl"
                shutil.copy2(events_file, dst)
                collected["tool_events_jsonl"] = str(dst)
                # Also use events.jsonl as the primary trajectory source
                collected["trajectory_json"] = str(dst)

        # Copy individual log files
        for f in logs_dir.iterdir():
            if not f.is_file():
                continue
            if f.name == "stdout.log":
                shutil.copy2(f, agent_dir / "stdout.log")
                collected["stdout_log"] = str(agent_dir / "stdout.log")
            elif f.name == "stderr.log":
                shutil.copy2(f, agent_dir / "stderr.log")
                collected["stderr_log"] = str(agent_dir / "stderr.log")
            elif f.name == "trajectory_export.log":
                shutil.copy2(f, artifacts_dir / f.name)
                collected["artifact_files"].append(str(artifacts_dir / f.name))
            elif f.name == "openclaw-agent.sqlite":
                dst = agent_dir / f.name
                if not dst.exists():
                    shutil.copy2(f, dst)
                    collected["artifact_files"].append(str(dst))
            elif f.name == "events.jsonl":
                if collected["tool_events_jsonl"] is None:
                    dst = agent_dir / "events.jsonl"
                    shutil.copy2(f, dst)
                    collected["tool_events_jsonl"] = str(dst)
                    if collected["trajectory_json"] is None:
                        collected["trajectory_json"] = str(dst)
            elif f.is_file():
                shutil.copy2(f, artifacts_dir / f.name)
                collected["artifact_files"].append(str(artifacts_dir / f.name))

    # 3. Copy output (recursive — VideoWeaver creates nested session directories)
    ws_output = workspace / "output"
    if ws_output.is_dir():
        for f in ws_output.rglob("*"):
            if f.is_file() and f.name != ".DS_Store":
                rel = f.relative_to(ws_output)
                dst = output_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                collected["output_files"].append(str(dst))

    return collected


def normalize_trajectory(raw_trajectory_path: Path, output_path: Path) -> bool:
    """Convert OpenClaw's native trace format to the normalized trajectory.json.

    The normalized format is a list of events:
    [
      {"timestamp": "...", "type": "model"},
      {"timestamp": "...", "type": "tool_call", "tool": "...", "arguments": {}},
      {"timestamp": "...", "type": "tool_result", "tool": "...", "status": "success"}
    ]

    If the raw trajectory is already in this format, it's copied as-is.
    The raw trajectory is always preserved (never discarded).
    """
    if not raw_trajectory_path.is_file():
        return False

    try:
        with open(raw_trajectory_path) as f:
            raw = json.load(f)
    except Exception:
        # If it's not JSON, try JSONL
        try:
            with open(raw_trajectory_path) as f:
                raw = [json.loads(line) for line in f if line.strip()]
        except Exception:
            return False

    normalized = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            event = {"timestamp": entry.get("timestamp", entry.get("ts", entry.get("time", "")))}

            entry_type = entry.get("type", "")
            data = entry.get("data", {}) if isinstance(entry.get("data"), dict) else {}

            # Check if this is a message with toolCall in content
            # OpenClaw puts tool calls inside message.content[] as {"type":"toolCall","name":"exec",...}
            msg = entry.get("message", {})
            content = msg.get("content", []) if isinstance(msg, dict) else []
            has_tool_call_in_content = False
            has_tool_result_in_content = False
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "toolCall":
                            has_tool_call_in_content = True
                        elif item.get("type") == "toolResult" or item.get("role") == "toolResult":
                            has_tool_result_in_content = True

            # Map OpenClaw event types to normalized types
            if has_tool_call_in_content or entry_type in ("tool.call", "tool_call", "toolCall"):
                event["type"] = "tool_call"
            elif has_tool_result_in_content or entry_type in ("tool.result", "tool_result", "toolResult"):
                event["type"] = "tool_result"
            elif entry_type in ("model", "tool_call", "tool_result", "message",
                                "model.completed", "session.ended"):
                if entry_type == "model.completed":
                    event["type"] = "model"
                elif entry_type == "session.ended":
                    event["type"] = "message"
                else:
                    event["type"] = entry_type
            elif entry.get("role") == "assistant":
                event["type"] = "model"
            elif entry.get("tool_calls") or entry.get("tool") or entry.get("toolName"):
                event["type"] = "tool_call"
            elif entry.get("tool_result") or entry.get("result"):
                event["type"] = "tool_result"
            else:
                event["type"] = entry_type or "message"

            if event["type"] == "tool_call":
                event["tool"] = (
                    entry.get("toolName")
                    or entry.get("tool")
                    or entry.get("tool_name")
                    or data.get("toolName")
                    or data.get("tool")
                    or "unknown"
                )
                event["arguments"] = (
                    entry.get("arguments")
                    or entry.get("args")
                    or data.get("arguments")
                    or data.get("args")
                    or {}
                )
            elif event["type"] == "tool_result":
                event["tool"] = (
                    entry.get("toolName")
                    or entry.get("tool")
                    or entry.get("tool_name")
                    or data.get("toolName")
                    or data.get("tool")
                    or "unknown"
                )
                success_val = entry.get("success", data.get("success"))
                if success_val is True:
                    event["status"] = "success"
                elif success_val is False:
                    event["status"] = "error"
                else:
                    event["status"] = entry.get("status", data.get("status", "unknown"))

            normalized.append(event)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return True
