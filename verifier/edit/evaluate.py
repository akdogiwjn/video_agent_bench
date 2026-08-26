#!/usr/bin/env python3
"""EDIT Verifier: AgenticVBench Repurpose verifier adapter.

Adapts our results layout to what the AgenticVBench repurpose verifier expects,
runs the official verifier (judge.py + aggregate.py + rubric.json), and
standardizes the output into verification_result.json.

The AgenticVBench repurpose verifier consists of:
- test.sh: orchestrates the verifier flow
- judge.py: VLM-based judge (Gemini + Anthropic) against per-task rubric
- aggregate.py: aggregates per-pillar JSONs into a single 0-1 reward
- rubric.json: per-task scoring rubric
- config.yaml: API key configuration

Key constraints:
- Verifier must NOT be mounted to the agent during execution
- Verifier runs AFTER the agent stops, in an isolated process
- Verifier needs GEMINI_API_KEY and ANTHROPIC_API_KEY
- Verifier needs source.mp4 (original) and repurpose.mp4 (agent output)

Usage:
    python3 verifier/edit/evaluate.py --results <run-dir> --task-id <task-id> [--upstream <path>]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def setup_verifier_workspace(
    results_dir: Path,
    task_id: str,
    upstream_root: Path | None = None,
) -> Path:
    """Set up the workspace layout that the AgenticVBench verifier expects.

    The verifier (test.sh) expects:
    - /tests/rubric.json
    - /tests/config.yaml
    - /tests/judge.py
    - /tests/aggregate.py
    - /tests/test.sh
    - /baked/source.mp4 (original source video)
    - /workspace/output/repurpose.mp4 (agent's output)

    We replicate this layout in a temporary directory.
    """
    if upstream_root is None:
        upstream_root = ROOT / "upstream" / "agentic_vbench" / "tasks_repurpose"

    task_dir = upstream_root / task_id
    tests_dir = task_dir / "steps" / "solve" / "tests"

    if not tests_dir.is_dir():
        raise FileNotFoundError(f"Verifier tests directory not found: {tests_dir}")

    # Create verifier workspace
    vw_dir = results_dir / "verification" / "avb_workspace"
    if vw_dir.exists():
        shutil.rmtree(vw_dir)
    vw_dir.mkdir(parents=True)

    # Copy verifier files
    tests_dst = vw_dir / "tests"
    tests_dst.mkdir()
    for f in ["rubric.json", "config.yaml", "judge.py", "aggregate.py", "test.sh"]:
        src = tests_dir / f
        if src.is_file():
            shutil.copy2(src, tests_dst / f)

    # Copy source video (from case materials)
    baked_dir = vw_dir / "baked"
    baked_dir.mkdir()
    case_materials = ROOT / "cases" / "edit" / "materials" / "source.mp4"
    if case_materials.is_file():
        shutil.copy2(case_materials, baked_dir / "source.mp4")

    # Copy brief.md if it exists
    brief_src = task_dir / "environment" / "brief.md"
    if brief_src.is_file():
        shutil.copy2(brief_src, baked_dir / "brief.md")

    # Create workspace/output with agent's output
    ws_output = vw_dir / "workspace" / "output"
    ws_output.mkdir(parents=True)
    agent_output = results_dir / "output" / "repurpose.mp4"
    if agent_output.is_file():
        shutil.copy2(agent_output, ws_output / "repurpose.mp4")

    # Create logs directories
    (vw_dir / "logs" / "verifier").mkdir(parents=True)
    (vw_dir / "logs" / "artifacts").mkdir(parents=True)

    return vw_dir


def run_verifier(vw_dir: Path, env_vars: dict[str, str] | None = None) -> dict:
    """Run the AgenticVBench verifier (test.sh).

    Returns the parsed reward.json if available, or an error result.
    """
    test_sh = vw_dir / "tests" / "test.sh"
    if not test_sh.is_file():
        return {"status": "error", "reason": "test.sh not found", "reward": 0.0}

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    # Set CUTBENCH_REPURPOSE_ONLY=1 as test.sh expects
    env["CUTBENCH_REPURPOSE_ONLY"] = "1"

    try:
        result = subprocess.run(
            ["bash", str(test_sh)],
            capture_output=True,
            text=True,
            timeout=1800,
            env=env,
            cwd=str(vw_dir),
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "Verifier timed out after 1800s", "reward": 0.0}
    except Exception as e:
        return {"status": "error", "reason": str(e), "reward": 0.0}

    # Parse reward.json
    reward_path = vw_dir / "logs" / "verifier" / "reward.json"
    if reward_path.is_file():
        try:
            with open(reward_path) as f:
                reward = json.load(f)
            return {
                "status": "completed",
                "reward": reward.get("reward", 0.0),
                "reason": reward.get("reason", ""),
                "details": reward.get("details", {}),
                "stdout": result.stdout[-2000:] if result.stdout else "",
                "stderr": result.stderr[-2000:] if result.stderr else "",
            }
        except Exception as e:
            return {"status": "parse_error", "reason": str(e), "reward": 0.0,
                    "stdout": result.stdout[-2000:] if result.stdout else ""}
    else:
        return {
            "status": "no_reward",
            "reason": "reward.json not produced",
            "reward": 0.0,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }


def evaluate(results_dir: Path, task_id: str, upstream_root: Path | None = None) -> dict:
    """Run the EDIT verifier and return standardized results."""
    result = {
        "benchmark": "AgenticVBench",
        "family": "repurpose",
        "task_id": task_id,
        "verifier_commit": None,
        "pass": False,
        "reward": 0.0,
        "details": {},
        "status": "unknown",
    }

    # Read commit
    commit_path = ROOT / "upstream" / "agentic_vbench" / "COMMIT"
    if commit_path.is_file():
        result["verifier_commit"] = commit_path.read_text().strip()

    # Check prerequisites
    agent_output = results_dir / "output" / "repurpose.mp4"
    if not agent_output.is_file():
        result["status"] = "no_output"
        result["details"]["reason"] = "Agent did not produce output/repurpose.mp4"
        return result

    case_source = ROOT / "cases" / "edit" / "materials" / "source.mp4"
    if not case_source.is_file():
        result["status"] = "no_source"
        result["details"]["reason"] = "Source material source.mp4 not downloaded yet"
        result["details"]["huggingface_url"] = (
            "https://huggingface.co/datasets/ameddserM/agentic_vbench_video_repurpose/resolve/main/materials/football.mp4"
        )
        return result

    # Check API keys
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_gemini or not has_anthropic:
        result["status"] = "missing_api_keys"
        result["details"]["reason"] = (
            "AgenticVBench repurpose verifier requires both GEMINI_API_KEY and ANTHROPIC_API_KEY"
        )
        result["details"]["has_gemini"] = has_gemini
        result["details"]["has_anthropic"] = has_anthropic
        return result

    # Set up verifier workspace
    try:
        vw_dir = setup_verifier_workspace(results_dir, task_id, upstream_root)
    except FileNotFoundError as e:
        result["status"] = "setup_error"
        result["details"]["reason"] = str(e)
        return result

    # Run verifier
    verifier_result = run_verifier(vw_dir)
    result["status"] = verifier_result["status"]
    result["reward"] = verifier_result.get("reward", 0.0)
    result["details"] = {k: v for k, v in verifier_result.items() if k not in ("stdout", "stderr")}
    result["pass"] = result["reward"] > 0.5

    return result


def main():
    parser = argparse.ArgumentParser(description="EDIT verifier (AgenticVBench Repurpose adapter)")
    parser.add_argument("--results", required=True, help="Path to results/<run-id>/ directory")
    parser.add_argument("--task-id", default="football", help="Task ID (default: football)")
    parser.add_argument("--upstream", default=None, help="Path to AgenticVBench tasks_repurpose root")
    args = parser.parse_args()

    results_dir = Path(args.results).resolve()
    upstream_root = Path(args.upstream) if args.upstream else None

    result = evaluate(results_dir, args.task_id, upstream_root)

    output_path = results_dir / "verification" / "verification_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"=== EDIT Verification ===")
    print(f"  task_id: {result['task_id']}")
    print(f"  status:  {result['status']}")
    print(f"  reward:  {result['reward']:.2f}")
    print(f"  pass:    {result['pass']}")
    if result["status"] != "completed":
        print(f"  reason:  {result['details'].get('reason', 'unknown')}")
    print(f"  output:  {output_path}")

    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
