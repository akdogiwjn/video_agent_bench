#!/usr/bin/env python3
"""V1 Verifier: Execution Integrity check.

Checks infrastructure-level execution integrity:
- OpenClaw was actually run and exited cleanly (exit_code == 0)
- Raw OpenClaw state / trajectory exists
- At least one tool call exists in trajectory (for video Agent workloads, >0 required)
- Correct final artifact exists (final.mp4 for GEN, repurpose.mp4 for EDIT)
- Final artifact was generated within the agent execution window (mtime check)
- stdout/stderr logs captured

Does NOT check business quality.

Usage:
    python3 verifier/verify_execution.py --results <run-dir> [--case-type gen|edit]
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path


def verify_execution(results_dir: Path, case_type: str | None = None) -> dict:
    """Check execution integrity of a run."""
    checks = {}
    passed = True

    manifest_path = results_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return {"pass": False, "checks": {"manifest": "MISSING"}, "error": "no manifest"}

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Determine case type if not specified
    if case_type is None:
        case_source = manifest.get("case_source", "")
        if "multi-benchmark" in case_source or manifest.get("benchmark") in ("VBench", "VideoWeaver"):
            case_type = "gen"
        else:
            case_type = "edit"

    expected_output = "final.mp4" if case_type == "gen" else "repurpose.mp4"

    # 1. OpenClaw was run and exited cleanly
    exit_code = manifest.get("agent_exit_code")
    checks["agent_exit_code"] = {
        "value": f"exit_code={exit_code}",
        "pass": exit_code == 0,
        "reason": "Agent must exit cleanly (exit_code == 0)" if exit_code != 0 else "",
    }

    # 2. Raw OpenClaw state exists
    raw_state_dir = results_dir / "agent" / "raw"
    has_raw_state = raw_state_dir.is_dir() and any(raw_state_dir.rglob("*"))
    checks["raw_openclaw_state"] = {
        "value": "present" if has_raw_state else "MISSING",
        "pass": has_raw_state,
        "reason": "Raw OpenClaw state must be persisted (mount /root/.openclaw)" if not has_raw_state else "",
    }

    # 3. Trajectory exists (events.jsonl or normalized_trajectory.json)
    events_path = results_dir / "agent" / "events.jsonl"
    trajectory_path = results_dir / "agent" / "trajectory.json"
    normalized_path = results_dir / "agent" / "normalized_trajectory.json"
    has_trajectory = (events_path.is_file() or trajectory_path.is_file()
                      or normalized_path.is_file())
    checks["trajectory_exists"] = {
        "value": ("events.jsonl" if events_path.is_file()
                  else "trajectory.json" if trajectory_path.is_file()
                  else "normalized_trajectory.json" if normalized_path.is_file()
                  else "MISSING"),
        "pass": has_trajectory,
        "reason": "Trajectory must exist to prove agent execution" if not has_trajectory else "",
    }

    # 4. Tool calls in trajectory (>0 required for video Agent workloads)
    # Check ALL trajectory sources and take the max count (most complete source wins)
    tool_call_count = 0
    for traj_file in [normalized_path, events_path, trajectory_path]:
        if not traj_file.is_file():
            continue
        try:
            with open(traj_file) as f:
                # Try JSON first, then JSONL
                try:
                    trajectory = json.load(f)
                except json.JSONDecodeError:
                    f.seek(0)
                    trajectory = [json.loads(line) for line in f if line.strip()]
            if isinstance(trajectory, list):
                count = sum(
                    1 for e in trajectory
                    if isinstance(e, dict) and (
                        e.get("type") in ("tool_call", "tool.call", "toolCall")
                        or any(
                            isinstance(item, dict) and item.get("type") == "toolCall"
                            for item in (e.get("message", {}).get("content", []) if isinstance(e.get("message"), dict) else [])
                            if isinstance(item, dict)
                        )
                    )
                )
                tool_call_count = max(tool_call_count, count)
        except Exception:
            pass
    checks["tool_calls_present"] = {
        "value": f"{tool_call_count} calls",
        "pass": tool_call_count > 0,
        "reason": "Video Agent workload must have at least 1 tool call" if tool_call_count == 0 else "",
    }

    # 5. Correct final artifact exists
    output_dir = results_dir / "output"
    expected_path = output_dir / expected_output
    checks["correct_final_artifact"] = {
        "value": expected_output if expected_path.is_file() else f"MISSING (expected {expected_output})",
        "pass": expected_path.is_file(),
        "reason": f"Expected {expected_output} for {case_type} case" if not expected_path.is_file() else "",
    }

    # 6. Final artifact mtime within agent window (no post-task repair)
    started_str = manifest.get("started_at", "")
    finished_str = manifest.get("finished_at", "")
    mtime_ok = False
    if expected_path.is_file() and started_str and finished_str:
        try:
            file_mtime = datetime.datetime.fromtimestamp(
                expected_path.stat().st_mtime, tz=datetime.timezone.utc
            )
            started_dt = datetime.datetime.fromisoformat(started_str)
            finished_dt = datetime.datetime.fromisoformat(finished_str)
            # File must be created after agent start and before or shortly after agent finish
            mtime_ok = started_dt <= file_mtime <= finished_dt + datetime.timedelta(minutes=5)
            checks["artifact_mtime_in_window"] = {
                "value": f"file_mtime={file_mtime.isoformat()}, window={started_str} to {finished_str}",
                "pass": mtime_ok,
                "reason": "Final artifact must be created within agent execution window (no post-task repair)" if not mtime_ok else "",
            }
        except Exception as e:
            checks["artifact_mtime_in_window"] = {
                "value": f"parse error: {e}",
                "pass": False,
                "reason": "Could not verify artifact mtime",
            }
    else:
        checks["artifact_mtime_in_window"] = {
            "value": "cannot verify",
            "pass": False,
            "reason": "Missing artifact or timestamps",
        }

    # 7. stdout/stderr captured
    stdout_path = results_dir / "agent" / "stdout.log"
    stderr_path = results_dir / "agent" / "stderr.log"
    checks["logs_captured"] = {
        "value": f"stdout={'yes' if stdout_path.is_file() else 'no'}, stderr={'yes' if stderr_path.is_file() else 'no'}",
        "pass": stdout_path.is_file() and stderr_path.is_file(),
        "reason": "Agent stdout and stderr must be captured" if not (stdout_path.is_file() and stderr_path.is_file()) else "",
    }

    for check in checks.values():
        if not check["pass"]:
            passed = False

    return {"pass": passed, "checks": checks, "case_type": case_type}


def main():
    parser = argparse.ArgumentParser(description="Verify execution integrity for a run")
    parser.add_argument("--results", required=True, help="Path to results/<run-id>/ directory")
    parser.add_argument("--case-type", default=None, choices=["gen", "edit"],
                        help="Case type (auto-detected if not specified)")
    args = parser.parse_args()

    results_dir = Path(args.results).resolve()
    result = verify_execution(results_dir, args.case_type)

    print("=== Execution Integrity Verification ===")
    for name, check in result["checks"].items():
        status = "PASS" if check["pass"] else "FAIL"
        reason = f" — {check.get('reason', '')}" if check.get("reason") else ""
        print(f"  {status}: {name} = {check['value']}{reason}")

    print(f"\nOverall: {'PASS' if result['pass'] else 'FAIL'}")
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
