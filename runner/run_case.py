#!/usr/bin/env python3
"""Main runner entry point for video_agent_bench.

Usage:
    python3 runner/run_case.py --case edit [--image video-agent-bench:1.0]
    python3 runner/run_case.py --case gen [--image video-agent-bench:1.0]

Responsibilities (infrastructure only — NO business logic):
1.  Read case manifest
2.  Verify all SHA256
3.  Create empty workspace
4.  Prepare OpenClaw temporary workspace
5.  Mount task/material/reference
6.  Mount allowed skills based on case manifest (+ dependency closure)
7.  Create Docker container
8.  Start OpenClaw (with openclaw.json, exec-approvals.json, state mount)
9.  Capture logs/trajectory (raw OpenClaw state persisted)
10. Stop Agent container
11. Call independent verifier (V0 provenance → V1 execution → benchmark verifier)
12. Write run_manifest.json (with full provenance chain)
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.workspace import (
    create_workspace,
    populate_task,
    populate_materials,
    populate_references,
    populate_skills,
)
from runner.provenance import (
    sha256_file,
    hash_directory,
    verify_case_manifest,
    write_run_manifest,
    now_iso,
)
from runner.openclaw_runner import (
    get_docker_image_id,
    get_openclaw_version,
    run_openclaw_in_docker,
    collect_trajectory,
    normalize_trajectory,
)


def load_case(case_type: str, case_id: str | None = None) -> tuple[Path, dict]:
    """Load case directory and manifest for the given case type (gen/edit).

    For GEN cases with subdirectory layout (e.g. cases/gen/gen_case_001/),
    case_id specifies which case to load. If case_id is not specified,
    the first case with a case_manifest.json is used.
    """
    base_dir = ROOT / "cases" / case_type

    # Try direct manifest first (EDIT layout: cases/edit/case_manifest.json)
    manifest_path = base_dir / "case_manifest.json"
    if manifest_path.is_file():
        case_dir = base_dir
    else:
        # Look for case subdirectories (GEN layout: cases/gen/gen_case_001/)
        case_dir = None
        if case_id:
            candidate = base_dir / case_id
            if (candidate / "case_manifest.json").is_file():
                case_dir = candidate
        else:
            # Auto-discover first available case
            for d in sorted(base_dir.iterdir()):
                if d.is_dir() and (d / "case_manifest.json").is_file():
                    case_dir = d
                    break

        if case_dir is None:
            print(f"ERROR: no case manifest found under {base_dir}", file=sys.stderr)
            sys.exit(1)
        manifest_path = case_dir / "case_manifest.json"

    with open(manifest_path) as f:
        manifest = json.load(f)

    if manifest.get("status") == "blocked":
        print(f"ERROR: case is blocked: {manifest.get('reason', 'unknown')}", file=sys.stderr)
        sys.exit(1)

    return case_dir, manifest


def determine_task_file(case_dir: Path, manifest: dict) -> str:
    """Determine the task file path relative to the workspace."""
    # Look for instruction.md in the task/ directory
    task_dir = case_dir / "task"
    if (task_dir / "instruction.md").is_file():
        return "task/instruction.md"
    if (task_dir / "instruction.txt").is_file():
        return "task/instruction.txt"
    # Fall back to any .txt or .md file in task/
    if task_dir.is_dir():
        for f in sorted(task_dir.iterdir()):
            if f.suffix in (".md", ".txt"):
                return f"task/{f.name}"
    print("ERROR: no task file found", file=sys.stderr)
    sys.exit(1)


def get_expected_output_filename(case_type: str) -> str:
    """Return the expected output filename for the case type."""
    if case_type == "gen":
        return "final.mp4"
    elif case_type == "edit":
        return "repurpose.mp4"
    return "final.mp4"


def run_verifier(case_type: str, results_dir: Path, case_dir: Path, image: str) -> dict:
    """Run the appropriate verifier after the agent has stopped.

    This completes the closed loop:
    Agent stop → collect output → independent verifier → verification_result.json

    Verifier runs in isolation — it has NO access to the agent's workspace
    or trajectory during execution (only to the output artifacts after).
    """
    verifier_script = ROOT / "verifier" / case_type / "evaluate.py"
    if not verifier_script.is_file():
        return {"status": "no_verifier", "reason": f"No verifier at {verifier_script}"}

    cmd = [sys.executable, str(verifier_script), "--results", str(results_dir)]

    if case_type == "gen":
        cmd.extend(["--case-dir", str(case_dir)])
    elif case_type == "edit":
        # EDIT needs task_id
        manifest_path = case_dir / "case_manifest.json"
        if manifest_path.is_file():
            with open(manifest_path) as f:
                m = json.load(f)
            task_id = m.get("case_id", "football")
            cmd.extend(["--task-id", task_id])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,
            cwd=str(ROOT),
        )
        # Parse verification_result.json
        vresult_path = results_dir / "verification" / "verification_result.json"
        if vresult_path.is_file():
            with open(vresult_path) as f:
                return json.load(f)
        return {
            "status": "verifier_error",
            "exit_code": result.returncode,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-1000:],
        }
    except subprocess.TimeoutExpired:
        return {"status": "verifier_timeout"}
    except Exception as e:
        return {"status": "verifier_exception", "error": str(e)}


def run_case(args):
    """Main execution flow."""
    case_type = args.case
    case_dir, manifest = load_case(case_type, getattr(args, 'case_id', None))

    print(f"=== video-agent-bench runner ===")
    print(f"  case type: {case_type}")
    print(f"  case id:   {manifest.get('case_id', 'unknown')}")
    print(f"  case source: {manifest.get('case_source', 'unknown')}")
    benchmark = manifest.get('benchmark', manifest.get('task_content_source', 'unknown'))
    print(f"  benchmark: {benchmark}")

    # 1. Verify SHA256
    print(f"\n[1/12] Verifying case files...")
    ok, errors = verify_case_manifest(case_dir)
    if not ok:
        print("  VERIFICATION FAILED:")
        for e in errors:
            print(f"    {e}")
        if not args.skip_verify:
            sys.exit(1)
        print("  (continuing due to --skip-verify)")
    else:
        print("  All files verified.")

    # 2. Create workspace + openclaw state dir
    run_id = f"{case_type}-{manifest.get('case_id', 'unknown')}-{uuid.uuid4().hex[:8]}"
    results_dir = ROOT / "results" / run_id
    workspace = results_dir / "workspace"
    openclaw_state_dir = results_dir / "openclaw_state"

    print(f"\n[2/12] Creating workspace: {workspace}")
    create_workspace(workspace)
    openclaw_state_dir.mkdir(parents=True, exist_ok=True)

    # 3-5. Populate task, materials, references
    print(f"[3/12] Populating task files...")
    task_files = populate_task(workspace, case_dir)
    for f in task_files:
        print(f"  {f.relative_to(workspace)}")

    print(f"[4/12] Populating materials...")
    material_files = populate_materials(workspace, case_dir)
    for f in material_files:
        print(f"  {f.relative_to(workspace)}")

    print(f"[5/12] Populating references...")
    ref_files = populate_references(workspace, case_dir)
    for f in ref_files:
        print(f"  {f.relative_to(workspace)}")

    # 6. Mount allowed skills (with dependency closure)
    print(f"[6/12] Mounting skills based on visible_capabilities (with dependency closure)...")
    visible_caps = manifest.get("visible_capabilities", [])
    skills_root = ROOT / "upstream" / "videoweaver" / "skills"
    skill_dirs = populate_skills(workspace, skills_root, visible_caps)
    for d in skill_dirs:
        print(f"  {d.relative_to(workspace)}")
    if not skill_dirs:
        print("  (no skills mounted — generic environment)")

    # 7. Determine task file
    task_file = determine_task_file(case_dir, manifest)
    print(f"\n[7/12] Task file: {task_file}")

    # 8. Get Docker image info + OpenClaw version
    image = args.image
    image_id = get_docker_image_id(image)
    print(f"[8/12] Docker image: {image} (id: {image_id[:24]})")

    # Compute hashes for run manifest
    task_sha = sha256_file(workspace / task_file)
    input_sha = hash_directory(workspace / "materials") if (workspace / "materials").is_dir() else {}
    if (workspace / "references").is_dir():
        input_sha.update(hash_directory(workspace / "references"))
    skills_sha = hash_directory(workspace / "skills") if (workspace / "skills").is_dir() else {}

    # Compute adaptation SHA256 if available
    adaptation_sha = ""
    adaptation_path = case_dir / "adaptation.json"
    if adaptation_path.is_file():
        adaptation_sha = sha256_file(adaptation_path)

    # Compute original prompt SHA256 if available
    original_prompt_sha = ""
    orig_prompt_path = case_dir / "source" / "original_prompt.txt"
    if orig_prompt_path.is_file():
        original_prompt_sha = sha256_file(orig_prompt_path)

    # Compute rubric/verifier SHA256
    verifier_sha = ""
    rubric_path = case_dir / "rubric" / "rubric_deterministic.json"
    if rubric_path.is_file():
        verifier_sha = sha256_file(rubric_path)

    # Get agent version
    agent_version = "unknown"
    if not args.dry_run:
        print(f"  Getting OpenClaw version...")
        agent_version = get_openclaw_version(image)
        print(f"  OpenClaw version: {agent_version}")

    # 9. Start OpenClaw
    started_at = now_iso()
    print(f"\n[9/12] Starting OpenClaw agent...")
    print(f"  model:   {args.model}")
    print(f"  timeout: {args.timeout}s")
    print(f"  openclaw state: {openclaw_state_dir}")

    if args.dry_run:
        print("  (dry run — skipping Docker execution)")
        result = {
            "exit_code": 0,
            "stdout": "[dry run] OpenClaw would be started here.",
            "stderr": "",
            "duration_seconds": 0.0,
            "container_name": "dry-run",
        }
    else:
        env_vars = {}
        # Pass through API keys from environment
        for key in [
            "ARK_API_KEY", "TOS_ACCESS_KEY", "TOS_SECRET_KEY",
            "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
            "ASR_APPID", "ASR_TOKEN", "APP_ID", "APP_SECRET",
            "VOLCENGINE_TTS_APPID", "VOLCENGINE_TTS_TOKEN",
        ]:
            val = os.environ.get(key)
            if val:
                env_vars[key] = val

        result = run_openclaw_in_docker(
            workspace=workspace,
            task_file=task_file,
            image=image,
            agent_model=args.model,
            timeout=args.timeout,
            env_vars=env_vars,
            openclaw_state_dir=openclaw_state_dir,
        )

    finished_at = now_iso()

    print(f"  exit code: {result['exit_code']}")
    print(f"  duration:  {result['duration_seconds']:.1f}s")

    # 10. Capture logs and trajectory (raw OpenClaw state persisted)
    print(f"\n[10/12] Capturing logs and trajectory...")
    logs_dir = workspace / "logs"
    logs_dir.mkdir(exist_ok=True)
    (logs_dir / "stdout.log").write_text(result["stdout"])
    (logs_dir / "stderr.log").write_text(result["stderr"])

    collected = collect_trajectory(workspace, results_dir, openclaw_state_dir)
    print(f"  raw openclaw state: {'yes' if collected.get('raw_openclaw_state') else 'no'}")
    print(f"  trajectory: {'yes' if collected.get('trajectory_json') else 'no'}")
    print(f"  output files: {len(collected['output_files'])}")
    for f in collected["output_files"]:
        print(f"    {f}")

    # Normalize trajectory if available
    if collected.get("trajectory_json"):
        norm_path = results_dir / "agent" / "normalized_trajectory.json"
        if normalize_trajectory(Path(collected["trajectory_json"]), norm_path):
            print(f"  normalized trajectory: {norm_path}")

    # 11. Call independent verifier (closed loop!)
    print(f"\n[11/12] Running verifier (isolated, post-agent)...")
    if args.dry_run:
        print("  (dry run — skipping verifier)")
        verifier_result = {"status": "skipped_dry_run", "pass": False, "reward": 0.0}
    else:
        verifier_result = run_verifier(case_type, results_dir, case_dir, image)
        v_status = verifier_result.get("status", "unknown")
        v_pass = verifier_result.get("pass", False)
        v_reward = verifier_result.get("reward", 0.0)
        print(f"  verifier status: {v_status}")
        print(f"  verifier reward: {v_reward:.2f}")
        print(f"  verifier pass:   {v_pass}")

    # 12. Write run_manifest.json (with full provenance chain)
    print(f"\n[12/12] Writing run_manifest.json...")

    # Determine benchmark name for manifest
    benchmark_name = manifest.get("benchmark", manifest.get("task_content_source", "unknown"))
    if manifest.get("case_source") == "multi-benchmark-derived":
        benchmark_name = manifest.get("task_content_source", "multi-benchmark-derived")

    # Get upstream commit + benchmark_sources
    upstream_commit = manifest.get("upstream_commit", "unknown")
    benchmark_sources = {}

    bs_path = case_dir / "benchmark_source.json"
    if bs_path.is_file():
        with open(bs_path) as f:
            bs = json.load(f)
        tcs = bs.get("task_content_source", {})
        if isinstance(tcs, dict):
            benchmark_sources["task_content"] = {
                "benchmark": tcs.get("benchmark", ""),
                "commit": tcs.get("commit", ""),
            }
            if upstream_commit == "unknown":
                upstream_commit = tcs.get("commit", "unknown")
        agb = bs.get("agentic_execution_basis", {})
        if isinstance(agb, dict):
            benchmark_sources["agentic_basis"] = {
                "benchmark": agb.get("benchmark", ""),
                "commit": agb.get("commit", ""),
            }
            if upstream_commit == "unknown":
                upstream_commit = agb.get("commit", "unknown")

    if not benchmark_sources:
        benchmark_sources["primary"] = {
            "benchmark": benchmark_name,
            "commit": upstream_commit,
        }

    run_manifest = {
        "benchmark": benchmark_name,
        "case_id": manifest.get("case_id", "unknown"),
        "case_source": manifest.get("case_source", "unknown"),
        "official_benchmark_case": manifest.get("official_benchmark_case", False),
        "benchmark_commit": upstream_commit,
        "benchmark_sources": benchmark_sources,
        "agent": "OpenClaw",
        "agent_version": agent_version,
        "agent_model": args.model,
        "docker_image": image,
        "docker_image_id": image_id,
        "task_sha256": task_sha,
        "instruction_sha256": task_sha,
        "original_prompt_sha256": original_prompt_sha,
        "adaptation_sha256": adaptation_sha,
        "input_sha256": input_sha,
        "skills_sha256": skills_sha,
        "verifier_sha256": verifier_sha,
        "started_at": started_at,
        "finished_at": finished_at,
        "agent_exit_code": result["exit_code"],
        "verifier_status": verifier_result.get("status", "unknown"),
        "verifier_pass": verifier_result.get("pass", False),
        "verifier_reward": verifier_result.get("reward", 0.0),
    }
    write_run_manifest(run_manifest, results_dir / "run_manifest.json")

    print(f"\n=== Run complete ===")
    print(f"  results: {results_dir}")
    print(f"  manifest: {results_dir / 'run_manifest.json'}")

    # Exit non-zero if agent failed OR verifier failed
    if not args.dry_run:
        if result["exit_code"] != 0:
            return result["exit_code"]
        if not verifier_result.get("pass", False):
            print(f"  WARNING: verifier did not pass (status={verifier_result.get('status')})")
            if args.fail_on_verifier_fail:
                return 1

    return result["exit_code"]


def main():
    parser = argparse.ArgumentParser(description="Run a video_agent_bench case")
    parser.add_argument("--case", required=True, choices=["gen", "edit"],
                        help="Case type to run")
    parser.add_argument("--case-id", default=None,
                        help="Case ID (for GEN cases with subdirectory layout, e.g. gen_case_001)")
    parser.add_argument("--image", default="video-agent-bench:1.0",
                        help="Docker image to use")
    parser.add_argument("--model", default=os.environ.get("AGENT_MODEL", "anthropic/claude-sonnet-4-6"),
                        help="Agent model")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("TIMEOUT", "3600")),
                        help="Agent timeout in seconds")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Docker execution (for testing infrastructure)")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Skip SHA256 verification (not recommended)")
    parser.add_argument("--fail-on-verifier-fail", action="store_true",
                        help="Exit non-zero if verifier does not pass")
    args = parser.parse_args()

    exit_code = run_case(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
