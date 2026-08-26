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


def run_openclaw_in_docker(
    workspace: Path,
    task_file: str,
    image: str,
    agent_model: str,
    timeout: int = 3600,
    env_vars: dict[str, str] | None = None,
) -> dict:
    """Run OpenClaw agent inside a Docker container.

    Mounts the workspace directory and runs the entrypoint.sh with the task file.
    Captures stdout, stderr, and collects trajectory artifacts.

    Returns a dict with:
        - exit_code: int
        - stdout: str
        - stderr: str
        - duration_seconds: float
    """
    workspace = Path(workspace).resolve()
    task_file_abs = str(workspace / task_file)

    # Docker mount: workspace -> /workspace
    volumes = {str(workspace): {"bind": "/workspace", "mode": "rw"}}

    # Environment variables
    env = {
        "AGENT_MODEL": agent_model,
        "TIMEOUT": str(timeout),
    }
    if env_vars:
        env.update(env_vars)

    # Build docker run command
    cmd = [
        "docker", "run", "--rm",
        "--name", f"video-agent-bench-{int(time.time())}",
    ]
    for k, v in env.items():
        cmd.extend(["-e", f"{k}={v}"])
    for host_path, bind in volumes.items():
        cmd.extend(["-v", f"{host_path}:{bind['bind']}:{bind['mode']}"])
    cmd.extend([image, task_file])

    started = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout + 300,  # extra 5 min for container overhead
    )
    duration = time.time() - started

    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_seconds": duration,
    }


def collect_trajectory(workspace: Path, results_dir: Path) -> dict:
    """Collect trajectory artifacts from the workspace.

    OpenClaw writes session data to ~/.openclaw/agents/<id>/sessions/.
    Inside the container, this is under /root/.openclaw/.
    We look for trajectory files in the logs directory and the output directory.
    """
    workspace = Path(workspace)
    results_dir = Path(results_dir)

    agent_dir = results_dir / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    output_dir = results_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts_dir = results_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    collected = {
        "stdout_log": None,
        "stderr_log": None,
        "trajectory_json": None,
        "tool_events_jsonl": None,
        "output_files": [],
        "artifact_files": [],
    }

    # Copy logs
    logs_dir = workspace / "logs"
    if logs_dir.is_dir():
        for f in logs_dir.iterdir():
            if f.name == "stdout.log":
                shutil.copy2(f, agent_dir / "stdout.log")
                collected["stdout_log"] = str(agent_dir / "stdout.log")
            elif f.name == "stderr.log":
                shutil.copy2(f, agent_dir / "stderr.log")
                collected["stderr_log"] = str(agent_dir / "stderr.log")
            elif f.name == "trajectory.json":
                shutil.copy2(f, agent_dir / "trajectory.json")
                collected["trajectory_json"] = str(agent_dir / "trajectory.json")
            elif f.name == "tool_events.jsonl":
                shutil.copy2(f, agent_dir / "tool_events.jsonl")
                collected["tool_events_jsonl"] = str(agent_dir / "tool_events.jsonl")
            elif f.is_file():
                shutil.copy2(f, artifacts_dir / f.name)
                collected["artifact_files"].append(str(artifacts_dir / f.name))

    # Copy output
    ws_output = workspace / "output"
    if ws_output.is_dir():
        for f in ws_output.iterdir():
            if f.is_file() and f.name != ".DS_Store":
                shutil.copy2(f, output_dir / f.name)
                collected["output_files"].append(str(output_dir / f.name))

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
            event = {"timestamp": entry.get("timestamp", entry.get("ts", ""))}

            entry_type = entry.get("type", "")
            if entry_type in ("model", "tool_call", "tool_result", "message"):
                event["type"] = entry_type
            elif entry.get("role") == "assistant":
                event["type"] = "model"
            elif entry.get("tool_calls") or entry.get("tool"):
                event["type"] = "tool_call"
            elif entry.get("tool_result") or entry.get("result"):
                event["type"] = "tool_result"
            else:
                event["type"] = entry_type or "message"

            if event["type"] == "tool_call":
                event["tool"] = entry.get("tool", entry.get("tool_name", "unknown"))
                event["arguments"] = entry.get("arguments", entry.get("args", {}))
            elif event["type"] == "tool_result":
                event["tool"] = entry.get("tool", entry.get("tool_name", "unknown"))
                event["status"] = entry.get("status", "unknown")

            normalized.append(event)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return True
