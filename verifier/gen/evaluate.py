#!/usr/bin/env python3
"""GEN Verifier: VideoWeaver PRM/ORM adapter.

Adapts our results layout to what the VideoWeaver evaluators expect,
calls the upstream evaluator, and standardizes the output into
verification_result.json.

VideoWeaver provides two evaluators:
- evaluation_PRM: Process/trace evaluation (planning, input processing,
  skill following, reference usage, clip merging)
- evaluation_ORM: Output/video evaluation (format, prompt adherence,
  visual/audio consistency, plot logic, reference fidelity)

This adapter:
1. Locates the VideoWeaver evaluation code (frozen in upstream/)
2. Converts our results layout → VideoWeaver expected layout
3. Invokes the upstream evaluator
4. Normalizes results into verification_result.json

Usage:
    python3 verifier/gen/evaluate.py --results <run-dir> [--upstream <path>]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def find_video_weaver_eval(upstream_root: Path | None = None) -> dict:
    """Locate VideoWeaver evaluation code in the upstream freeze.

    Note: In Milestone 1, we only froze the skills/ directory.
    The evaluation code (evaluation_PRM, evaluation_ORM) lives in
    AutomaticSkillOptimization/ and needs to be fetched separately.
    """
    if upstream_root is None:
        upstream_root = ROOT / "upstream" / "videoweaver"

    eval_prm = upstream_root / "AutomaticSkillOptimization" / "evaluation_PRM"
    eval_orm = upstream_root / "AutomaticSkillOptimization" / "evaluation_ORM"

    return {
        "evaluation_PRM_path": str(eval_prm) if eval_prm.is_dir() else None,
        "evaluation_ORM_path": str(eval_orm) if eval_orm.is_dir() else None,
        "available": eval_prm.is_dir() or eval_orm.is_dir(),
        "note": (
            "VideoWeaver evaluation code (AutomaticSkillOptimization/) was not "
            "frozen in Milestone 1 (only skills/ were frozen). Fetch it from "
            "the upstream repo at the same commit to enable GEN verification."
        ),
    }


def convert_results_layout(results_dir: Path, output_dir: Path) -> dict:
    """Convert our results layout to what VideoWeaver evaluators expect.

    VideoWeaver expects:
    - final.mp4 in the artifact directory
    - ReAct_process.json / ReAct_process.txt (execution trace)
    - basic_results.json
    - Intermediate images/videos/audio
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy output files
    our_output = results_dir / "output"
    if our_output.is_dir():
        for f in our_output.iterdir():
            if f.is_file() and f.name != ".DS_Store":
                import shutil
                shutil.copy2(f, output_dir / f.name)

    # Copy trajectory
    agent_dir = results_dir / "agent"
    if agent_dir.is_dir():
        traj = agent_dir / "trajectory.json"
        if traj.is_file():
            import shutil
            shutil.copy2(traj, output_dir / "ReAct_process.json")

    return {"converted_dir": str(output_dir), "note": "Layout converted for VideoWeaver evaluator."}


def evaluate(results_dir: Path, upstream_root: Path | None = None) -> dict:
    """Run the GEN verifier and return standardized results."""
    eval_info = find_video_weaver_eval(upstream_root)

    result = {
        "benchmark": "VideoWeaver",
        "verifier_commit": None,
        "pass": False,
        "reward": 0.0,
        "details": {},
        "status": "unknown",
    }

    if not eval_info["available"]:
        result["status"] = "blocked"
        result["details"]["reason"] = eval_info["note"]
        result["details"]["evaluation_PRM_path"] = eval_info["evaluation_PRM_path"]
        result["details"]["evaluation_ORM_path"] = eval_info["evaluation_ORM_path"]
        return result

    # Convert layout
    converted_dir = results_dir / "verification" / "vw_converted"
    layout = convert_results_layout(results_dir, converted_dir)

    # Run PRM (process evaluation)
    prm_result = run_evaluator(
        eval_info["evaluation_PRM_path"],
        converted_dir,
        results_dir / "verification" / "prm_result.json",
    )

    # Run ORM (output evaluation)
    orm_result = run_evaluator(
        eval_info["evaluation_ORM_path"],
        converted_dir,
        results_dir / "verification" / "orm_result.json",
    )

    result["details"]["process_evaluation"] = prm_result
    result["details"]["output_evaluation"] = orm_result

    # Aggregate
    prm_reward = prm_result.get("reward", 0.0)
    orm_reward = orm_result.get("reward", 0.0)
    result["reward"] = (prm_reward + orm_reward) / 2
    result["pass"] = result["reward"] > 0.5
    result["status"] = "evaluated"

    return result


def run_evaluator(eval_path: str | None, artifact_dir: Path, output_path: Path) -> dict:
    """Run a single VideoWeaver evaluator."""
    if eval_path is None:
        return {"status": "not_available", "reward": 0.0}

    try:
        result = subprocess.run(
            ["python3", eval_path, "--artifact-dir", str(artifact_dir)],
            capture_output=True, text=True, timeout=600,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.stdout)

        # Try to parse JSON from output
        try:
            return json.loads(result.stdout)
        except Exception:
            return {"status": "completed", "stdout": result.stdout[:1000], "reward": 0.0}
    except Exception as e:
        return {"status": "error", "error": str(e), "reward": 0.0}


def main():
    parser = argparse.ArgumentParser(description="GEN verifier (VideoWeaver PRM/ORM adapter)")
    parser.add_argument("--results", required=True, help="Path to results/<run-id>/ directory")
    parser.add_argument("--upstream", default=None, help="Path to VideoWeaver upstream root")
    args = parser.parse_args()

    results_dir = Path(args.results).resolve()
    upstream_root = Path(args.upstream) if args.upstream else None

    result = evaluate(results_dir, upstream_root)

    output_path = results_dir / "verification" / "verification_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"=== GEN Verification ===")
    print(f"  status: {result['status']}")
    print(f"  reward: {result['reward']:.2f}")
    print(f"  pass:   {result['pass']}")
    if result["status"] == "blocked":
        print(f"  reason: {result['details'].get('reason', 'unknown')}")
    print(f"  output: {output_path}")

    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
