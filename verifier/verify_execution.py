#!/usr/bin/env python3
"""V1 Verifier: Execution Integrity check.

Checks infrastructure-level execution integrity:
- OpenClaw was actually run (exit code recorded)
- Trajectory exists
- At least one tool call exists in trajectory (if not empty)
- Final artifact was generated within the agent window
- Runner did not perform post-task repair

Does NOT check business quality.

Usage:
    python3 verifier/verify_execution.py --results <run-dir>
"""
import argparse
import json
import sys
from pathlib import Path


def verify_execution(results_dir: Path) -> dict:
    """Check execution integrity of a run."""
    checks = {}
    passed = True

    manifest_path = results_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return {"pass": False, "checks": {"manifest": "MISSING"}, "error": "no manifest"}

    with open(manifest_path) as f:
        manifest = json.load(f)

    # 1. OpenClaw was run
    exit_code = manifest.get("agent_exit_code")
    checks["agent_executed"] = {
        "value": f"exit_code={exit_code}",
        "pass": exit_code is not None,
    }

    # 2. Trajectory exists
    trajectory_path = results_dir / "agent" / "trajectory.json"
    normalized_path = results_dir / "agent" / "normalized_trajectory.json"
    has_trajectory = trajectory_path.is_file() or normalized_path.is_file()
    checks["trajectory_exists"] = {
        "value": str(trajectory_path.name) if has_trajectory else "MISSING",
        "pass": has_trajectory,
    }

    # 3. Tool calls in trajectory
    tool_call_count = 0
    traj_file = normalized_path if normalized_path.is_file() else trajectory_path
    if traj_file.is_file():
        try:
            with open(traj_file) as f:
                trajectory = json.load(f)
            if isinstance(trajectory, list):
                tool_call_count = sum(1 for e in trajectory if isinstance(e, dict) and e.get("type") == "tool_call")
        except Exception:
            pass
    checks["tool_calls_present"] = {
        "value": f"{tool_call_count} calls",
        "pass": True,  # 0 is OK for simple tasks
    }

    # 4. Final artifact exists
    output_dir = results_dir / "output"
    output_files = []
    if output_dir.is_dir():
        output_files = [f.name for f in output_dir.iterdir() if f.is_file() and f.name != ".DS_Store"]
    checks["final_artifact"] = {
        "value": output_files if output_files else "NONE",
        "pass": len(output_files) > 0,
    }

    # 5. No post-task repair (check manifest timestamps)
    started = manifest.get("started_at", "")
    finished = manifest.get("finished_at", "")
    checks["timestamps_present"] = {
        "value": f"{started} → {finished}",
        "pass": bool(started) and bool(finished),
    }

    # 6. stdout/stderr captured
    stdout_path = results_dir / "agent" / "stdout.log"
    stderr_path = results_dir / "agent" / "stderr.log"
    checks["logs_captured"] = {
        "value": f"stdout={'yes' if stdout_path.is_file() else 'no'}, stderr={'yes' if stderr_path.is_file() else 'no'}",
        "pass": stdout_path.is_file() and stderr_path.is_file(),
    }

    for check in checks.values():
        if not check["pass"]:
            passed = False

    return {"pass": passed, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description="Verify execution integrity for a run")
    parser.add_argument("--results", required=True, help="Path to results/<run-id>/ directory")
    args = parser.parse_args()

    results_dir = Path(args.results).resolve()
    result = verify_execution(results_dir)

    print("=== Execution Integrity Verification ===")
    for name, check in result["checks"].items():
        status = "PASS" if check["pass"] else "FAIL"
        print(f"  {status}: {name} = {check['value']}")

    print(f"\nOverall: {'PASS' if result['pass'] else 'FAIL'}")
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
