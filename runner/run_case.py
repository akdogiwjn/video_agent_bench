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

# Auto-load config.env if it exists (before any env var reads)
_config_env = ROOT / "config" / "config.env"
if _config_env.is_file():
    with open(_config_env) as f:
        for _line in f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key = _key.strip()
                _val = _val.strip()
                if _val and _key not in os.environ:
                    os.environ[_key] = _val

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

    # If case_id is specified, look for subdirectory first (e.g. cases/edit/football_short/)
    if case_id:
        candidate = base_dir / case_id
        if (candidate / "case_manifest.json").is_file():
            case_dir = candidate
            manifest_path = case_dir / "case_manifest.json"
            with open(manifest_path) as f:
                manifest = json.load(f)
            if manifest.get("status") == "blocked":
                print(f"ERROR: case is blocked: {manifest.get('reason', 'unknown')}", file=sys.stderr)
                sys.exit(1)
            return case_dir, manifest

    # Try direct manifest (EDIT layout: cases/edit/case_manifest.json)
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


def run_verifier_pipeline(case_type: str, results_dir: Path, case_dir: Path, image: str) -> dict:
    """Run the full verifier pipeline: V0 → V1 → V2.

    V0: Provenance verification (benchmark commit, SHA256, agent version)
    V1: Execution integrity (exit code, trajectory, tool calls, artifact mtime)
    V2: Benchmark verifier (GEN project-defined rubric / EDIT AgenticVBench verifier)

    Each stage writes its own result file under results/verification/.
    Final verification_result.json aggregates all three.
    """
    verif_dir = results_dir / "verification"
    verif_dir.mkdir(parents=True, exist_ok=True)

    pipeline_result = {
        "benchmark": case_type,
        "pass": False,
        "reward": 0.0,
        "status": "unknown",
        "details": {
            "v0_provenance": {},
            "v1_execution": {},
            "v2_benchmark": {},
        },
    }

    # V0: Provenance
    print("  [V0] Provenance verification...")
    v0_script = ROOT / "verifier" / "verify_provenance.py"
    if v0_script.is_file():
        try:
            v0 = subprocess.run(
                [sys.executable, str(v0_script), "--results", str(results_dir)],
                capture_output=True, text=True, timeout=60, cwd=str(ROOT),
            )
            v0_result_path = verif_dir / "provenance.json"
            v0_data = {
                "pass": v0.returncode == 0,
                "stdout": v0.stdout[-1000:],
                "stderr": v0.stderr[-500:] if v0.stderr else "",
            }
            with open(v0_result_path, "w") as f:
                json.dump(v0_data, f, indent=2)
            pipeline_result["details"]["v0_provenance"] = v0_data
            print(f"    {'PASS' if v0_data['pass'] else 'FAIL'}: provenance")
        except Exception as e:
            pipeline_result["details"]["v0_provenance"] = {"pass": False, "error": str(e)}
            print(f"    ERROR: provenance — {e}")
    else:
        pipeline_result["details"]["v0_provenance"] = {"pass": False, "error": "script not found"}
        print(f"    SKIP: provenance script not found")

    # V1: Execution integrity
    print("  [V1] Execution integrity verification...")
    v1_script = ROOT / "verifier" / "verify_execution.py"
    if v1_script.is_file():
        try:
            v1 = subprocess.run(
                [sys.executable, str(v1_script), "--results", str(results_dir),
                 "--case-type", case_type],
                capture_output=True, text=True, timeout=60, cwd=str(ROOT),
            )
            v1_result_path = verif_dir / "execution_integrity.json"
            v1_data = {
                "pass": v1.returncode == 0,
                "stdout": v1.stdout[-1000:],
                "stderr": v1.stderr[-500:] if v1.stderr else "",
            }
            with open(v1_result_path, "w") as f:
                json.dump(v1_data, f, indent=2)
            pipeline_result["details"]["v1_execution"] = v1_data
            print(f"    {'PASS' if v1_data['pass'] else 'FAIL'}: execution integrity")
        except Exception as e:
            pipeline_result["details"]["v1_execution"] = {"pass": False, "error": str(e)}
            print(f"    ERROR: execution — {e}")
    else:
        pipeline_result["details"]["v1_execution"] = {"pass": False, "error": "script not found"}

    # V2: Benchmark verifier
    print("  [V2] Benchmark verifier...")
    v2_result = run_benchmark_verifier(case_type, results_dir, case_dir, image)
    # V2 writes benchmark_result.json from inside Docker (root-owned)
    # Try to read it; if write fails due to permissions, just use the returned data
    v2_result_path = verif_dir / "benchmark_result.json"
    try:
        with open(v2_result_path, "w") as f:
            json.dump(v2_result, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except PermissionError:
        # Docker root wrote it; use the data we got back from subprocess
        pass
    pipeline_result["details"]["v2_benchmark"] = {
        "pass": v2_result.get("pass", False),
        "status": v2_result.get("status", "unknown"),
        "reward": v2_result.get("reward", 0.0),
    }
    print(f"    {'PASS' if v2_result.get('pass') else 'FAIL'}: benchmark (status={v2_result.get('status')}, reward={v2_result.get('reward', 0):.2f})")

    # Overall pass = V0 AND V1 AND V2
    v0_pass = pipeline_result["details"]["v0_provenance"].get("pass", False)
    v1_pass = pipeline_result["details"]["v1_execution"].get("pass", False)
    v2_pass = pipeline_result["details"]["v2_benchmark"].get("pass", False)
    pipeline_result["pass"] = v0_pass and v1_pass and v2_pass
    pipeline_result["status"] = "pass" if pipeline_result["pass"] else "fail"
    pipeline_result["reward"] = pipeline_result["details"]["v2_benchmark"].get("reward", 0.0)

    # Write aggregated result
    final_path = verif_dir / "verification_result.json"
    with open(final_path, "w") as f:
        json.dump(pipeline_result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return pipeline_result


def run_benchmark_verifier(case_type: str, results_dir: Path, case_dir: Path, image: str) -> dict:
    """Run the benchmark-specific verifier (V2) inside a Docker container.

    This ensures the verifier has:
    - Network access via proxy (for VLM/Omni API calls)
    - Whisper pre-cached (for F-09/S-01 transcript comparison)
    - scenedetect installed (for GEN C-02)
    - All Python dependencies (numpy, PIL, openai, etc.)
    """
    verifier_script = ROOT / "verifier" / case_type / "evaluate.py"
    if not verifier_script.is_file():
        return {"status": "no_verifier", "reason": f"No verifier at {verifier_script}"}

    # Mount results dir + case dir + repo root into container
    host_results = str(results_dir.resolve())
    host_case_dir = str(case_dir.resolve())
    host_root = str(ROOT.resolve())

    # Build docker run command — verifier runs inside container
    cmd = [
        "docker", "run", "--rm",
        "--network", "host",
        "--entrypoint", "/bin/bash",
        "--name", f"vab-verifier-{case_type}-{uuid.uuid4().hex[:8]}",
        "-v", f"{host_results}:/results:rw",
        "-v", f"{host_case_dir}:/case:ro",
        "-v", f"{host_root}:/repo:ro",
        "-w", "/repo",
        "-e", f"DEEPSEEK_API_KEY={os.environ.get('DEEPSEEK_API_KEY', '')}",
        "-e", f"DASHSCOPE_API_KEY={os.environ.get('DASHSCOPE_API_KEY', '')}",
        "-e", f"DASHSCOPE_BASE_URL={os.environ.get('DASHSCOPE_BASE_URL', '')}",
        "-e", f"DASHSCOPE_NATIVE_BASE_URL={os.environ.get('DASHSCOPE_NATIVE_BASE_URL', '')}",
        "-e", f"VLM_MODEL={os.environ.get('VLM_MODEL', '')}",
        "-e", f"VLM_BASE_URL={os.environ.get('VLM_BASE_URL', '')}",
        "-e", f"OMNI_MODEL={os.environ.get('OMNI_MODEL', '')}",
        "-e", f"IMAGE_GEN_MODEL={os.environ.get('IMAGE_GEN_MODEL', '')}",
        "-e", f"VIDEO_GEN_MODEL={os.environ.get('VIDEO_GEN_MODEL', '')}",
        "-e", f"EDIT_VERIFIER_MODE={os.environ.get('EDIT_VERIFIER_MODE', 'adapted')}",
        "-e", "GEMINI_API_KEY=" + os.environ.get("GEMINI_API_KEY", ""),
        "-e", "ANTHROPIC_API_KEY=" + os.environ.get("ANTHROPIC_API_KEY", ""),
    ]

    # Add proxy env if available
    for proxy_var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
        val = os.environ.get(proxy_var)
        if val:
            cmd.extend(["-e", f"{proxy_var}={val}"])

    # Add Python path so verifier can import tools/providers
    cmd.extend([
        "-e", "PYTHONPATH=/repo",
        image,
        "-c",
    ])

    # Build the Python command
    if case_type == "gen":
        py_cmd = f"python3 /repo/verifier/gen/evaluate.py --results /results --case-dir /case"
    else:
        # EDIT: task_id from manifest
        manifest_path = case_dir / "case_manifest.json"
        task_id = "football"
        if manifest_path.is_file():
            with open(manifest_path) as f:
                m = json.load(f)
            task_id = m.get("case_id", "football")
        py_cmd = f"python3 /repo/verifier/edit/evaluate.py --results /results --task-id {task_id} --case-dir /case --image {image}"

    cmd.append(py_cmd)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
        )
        # Read benchmark_result.json written by verifier
        benchmark_path = results_dir / "verification" / "benchmark_result.json"
        if benchmark_path.is_file():
            with open(benchmark_path) as f:
                return json.load(f)
        # Fallback: read verification_result.json
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
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}_{case_type}-{manifest.get('case_id', 'unknown')}"
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
        # Pass through all configured environment variables to Docker container
        # Provider-specific keys — no ARK/Volcengine by default
        for key in [
            # Agent (DeepSeek)
            "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
            # DashScope (VLM, image-gen, video-gen, omni)
            "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_NATIVE_BASE_URL",
            "VLM_PROVIDER", "VLM_MODEL", "VLM_BASE_URL",
            "OMNI_PROVIDER", "OMNI_MODEL",
            "IMAGE_GEN_PROVIDER", "IMAGE_GEN_MODEL",
            "VIDEO_GEN_PROVIDER", "VIDEO_GEN_MODEL",
            # EDIT verifier mode
            "EDIT_VERIFIER_MODE",
            # Optional: official AgenticVBench verifier
            "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
            # ASR (local Whisper, no key needed, but pass through for Volcengine ASR if configured)
            "ASR_APPID", "ASR_TOKEN",
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
            case_type=case_type,
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

    # --- Compute all provenance fields for preliminary manifest ---
    benchmark_name = manifest.get("benchmark", manifest.get("task_content_source", "unknown"))
    if manifest.get("case_source") == "multi-benchmark-derived":
        benchmark_name = manifest.get("task_content_source", "multi-benchmark-derived")
    upstream_commit = manifest.get("upstream_commit", "unknown")
    benchmark_sources = {}
    bs_path = case_dir / "benchmark_source.json"
    if bs_path.is_file():
        with open(bs_path) as f:
            bs = json.load(f)
        if bs.get("case_source") == "official" or bs.get("official_benchmark_case"):
            benchmark_name = bs.get("benchmark", benchmark_name)
            upstream_commit = bs.get("upstream_commit", upstream_commit)
            benchmark_sources["primary"] = {"benchmark": bs.get("benchmark", benchmark_name), "commit": bs.get("upstream_commit", upstream_commit), "case_source": "official"}
        else:
            tcs = bs.get("task_content_source", {})
            if isinstance(tcs, dict) and tcs.get("benchmark"):
                benchmark_sources["task_content"] = {"benchmark": tcs.get("benchmark", ""), "commit": tcs.get("commit", "")}
                if upstream_commit == "unknown": upstream_commit = tcs.get("commit", "unknown")
            agb = bs.get("agentic_execution_basis", {})
            if isinstance(agb, dict) and agb.get("benchmark"):
                benchmark_sources["agentic_basis"] = {"benchmark": agb.get("benchmark", ""), "commit": agb.get("commit", "")}
                if upstream_commit == "unknown": upstream_commit = agb.get("commit", "unknown")
    if not benchmark_sources:
        benchmark_sources["primary"] = {"benchmark": benchmark_name, "commit": upstream_commit}
    import hashlib as _hl
    verifier_hasher = _hl.sha256()
    # Collect all verifier files, then sort for deterministic ordering
    # (must match verify_provenance.py which sorts by str(path))
    _vf_list = [ROOT / "verifier" / case_type / "evaluate.py",
                case_dir / "rubric" / "rubric_deterministic.json"]
    if case_type == "edit":
        task_id = manifest.get("case_id", "football")
        for fname in ["rubric.json", "judge.py", "aggregate.py", "test.sh", "config.yaml"]:
            _vf_list.append(ROOT / "upstream" / "agentic_vbench" / "tasks_repurpose" / task_id / "steps" / "solve" / "tests" / fname)
    for vf in sorted(_vf_list, key=lambda p: str(p)):
        if vf.is_file():
            verifier_hasher.update(str(vf.relative_to(ROOT)).encode()); verifier_hasher.update(b"\0")
            verifier_hasher.update(vf.read_bytes()); verifier_hasher.update(b"\0")
    verifier_sha = verifier_hasher.hexdigest()

    # --- Write PRELIMINARY run_manifest.json BEFORE V0/V1/V2 ---
    print(f"\n[11a/12] Writing preliminary run_manifest.json (before V0/V1)...")
    run_manifest = {
        "benchmark": benchmark_name, "case_id": manifest.get("case_id", "unknown"),
        "case_source": manifest.get("case_source", "unknown"),
        "official_benchmark_case": manifest.get("official_benchmark_case", False),
        "benchmark_commit": upstream_commit, "benchmark_sources": benchmark_sources,
        "agent": "OpenClaw", "agent_version": agent_version, "agent_model": args.model,
        "docker_image": image, "docker_image_id": image_id,
        "task_sha256": task_sha, "instruction_sha256": task_sha,
        "original_prompt_sha256": original_prompt_sha, "adaptation_sha256": adaptation_sha,
        "input_sha256": input_sha, "skills_sha256": skills_sha, "verifier_sha256": verifier_sha,
        "tools_sha256": hash_directory(workspace / "tools") if (workspace / "tools").is_dir() else {},
        "runtime_skills_sha256": hash_directory(ROOT / "runtime_skills") if (ROOT / "runtime_skills").is_dir() else {},
        "started_at": started_at, "finished_at": finished_at,
        "agent_exit_code": result["exit_code"],
        "verifier_status": "pending", "verifier_pass": False, "verifier_reward": 0.0,
        # Provider metadata — records which backends were used (no API keys)
        "providers": {
            "agent_llm": {
                "provider": "deepseek",
                "model": "deepseek/deepseek-v4-flash",
            },
            "vlm": {
                "provider": os.environ.get("VLM_PROVIDER", "dashscope"),
                "model": os.environ.get("VLM_MODEL", ""),
            },
            "image_generation": {
                "provider": os.environ.get("IMAGE_GEN_PROVIDER", "dashscope"),
                "model": os.environ.get("IMAGE_GEN_MODEL", ""),
            },
            "video_generation": {
                "provider": os.environ.get("VIDEO_GEN_PROVIDER", "dashscope"),
                "model": os.environ.get("VIDEO_GEN_MODEL", ""),
            },
        },
        "skill_backend_adapted": True,
        "skill_source": "VideoWeaver",
        "edit_verifier_mode": os.environ.get("EDIT_VERIFIER_MODE", "adapted"),
    }
    write_run_manifest(run_manifest, results_dir / "run_manifest.json")

    # 11b. Run verifier pipeline: V0 → V1 → V2
    print(f"\n[11b/12] Running verifier pipeline (V0→V1→V2, isolated, post-agent)...")
    if args.dry_run:
        print("  (dry run — skipping verifier)")
        verifier_result = {"benchmark": case_type, "pass": False, "status": "skipped_dry_run",
                           "reward": 0.0, "details": {}}
    else:
        verifier_result = run_verifier_pipeline(case_type, results_dir, case_dir, image)
        print(f"  overall: {'PASS' if verifier_result.get('pass') else 'FAIL'}")

    # 12. Write FINAL run_manifest.json with verifier results
    print(f"\n[12/12] Writing final run_manifest.json (with verifier results)...")
    run_manifest["verifier_status"] = verifier_result.get("status", "unknown")
    run_manifest["verifier_pass"] = verifier_result.get("pass", False)
    run_manifest["verifier_reward"] = verifier_result.get("reward", 0.0)
    write_run_manifest(run_manifest, results_dir / "run_manifest.json")


    print(f"\n=== Run complete ===")
    print(f"  results: {results_dir}")
    print(f"  manifest: {results_dir / 'run_manifest.json'}")

    # Exit non-zero if agent failed OR verifier failed (fail-close by default)
    if not args.dry_run:
        if result["exit_code"] != 0:
            return result["exit_code"]
        if not verifier_result.get("pass", False):
            v_status = verifier_result.get("status", "unknown")
            print(f"  FAIL: verifier pipeline did not pass (status={v_status})")
            if not args.allow_verifier_fail:
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
    parser.add_argument("--model", default=os.environ.get("AGENT_MODEL", "deepseek/deepseek-v4-flash"),
                        help="Agent model")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("TIMEOUT", "3600")),
                        help="Agent timeout in seconds")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Docker execution (for testing infrastructure)")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Skip SHA256 verification (not recommended)")
    parser.add_argument("--allow-verifier-fail", action="store_true",
                        help="Continue even if verifier does not pass (default: fail-close)")
    args = parser.parse_args()

    exit_code = run_case(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
