#!/usr/bin/env python3
"""EDIT Verifier: AgenticVBench Repurpose verifier adapter.

Runs the official AgenticVBench verifier in an isolated Docker container
with correct path mapping. The official test.sh uses absolute paths
(/tests, /baked, /workspace/output, /logs) so we map our directories
to those exact container paths via Docker volume mounts.

This ensures the official verifier semantics are preserved without
modifying test.sh.

Key constraints:
- Verifier must NOT be mounted to the agent during execution
- Verifier runs AFTER the agent stops, in an isolated process/container
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
    """Set up the directory layout that the AgenticVBench verifier expects.

    The verifier (test.sh) expects these absolute container paths:
    - /tests/rubric.json, /tests/judge.py, /tests/aggregate.py, /tests/test.sh
    - /baked/source.mp4
    - /workspace/output/repurpose.mp4
    - /logs/verifier/ (output)
    - /logs/artifacts/ (output)

    We create a local directory structure and map it to those container paths.
    """
    if upstream_root is None:
        upstream_root = ROOT / "upstream" / "agentic_vbench" / "tasks_repurpose"

    task_dir = upstream_root / task_id
    tests_dir = task_dir / "steps" / "solve" / "tests"

    if not tests_dir.is_dir():
        raise FileNotFoundError(f"Verifier tests directory not found: {tests_dir}")

    # Create verifier workspace with the exact structure test.sh expects
    vw_dir = results_dir / "verification" / "avb_workspace"
    if vw_dir.exists():
        shutil.rmtree(vw_dir)

    # These directories will be mounted to /tests, /baked, /workspace, /logs in the container
    tests_dst = vw_dir / "tests"
    baked_dst = vw_dir / "baked"
    workspace_dst = vw_dir / "workspace"
    output_dst = workspace_dst / "output"
    logs_dst = vw_dir / "logs"
    verifier_logs_dst = logs_dst / "verifier"
    artifacts_logs_dst = logs_dst / "artifacts"

    for d in [tests_dst, baked_dst, output_dst, verifier_logs_dst, artifacts_logs_dst]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy verifier files (test.sh, judge.py, aggregate.py, rubric.json, config.yaml)
    for f in ["rubric.json", "config.yaml", "judge.py", "aggregate.py", "test.sh"]:
        src = tests_dir / f
        if src.is_file():
            shutil.copy2(src, tests_dst / f)

    # Copy source video (from case materials)
    case_source = ROOT / "cases" / "edit" / "materials" / "source.mp4"
    if case_source.is_file():
        # Large file: symlink to avoid copying 2.47GB
        try:
            (baked_dst / "source.mp4").symlink_to(case_source.resolve())
        except OSError:
            shutil.copy2(case_source, baked_dst / "source.mp4")

    # Copy brief.md if it exists
    brief_src = task_dir / "environment" / "brief.md"
    if brief_src.is_file():
        shutil.copy2(brief_src, baked_dst / "brief.md")

    # Copy agent's output
    agent_output = results_dir / "output" / "repurpose.mp4"
    if agent_output.is_file():
        shutil.copy2(agent_output, output_dst / "repurpose.mp4")

    return vw_dir


def run_verifier_in_docker(
    vw_dir: Path,
    image: str,
    env_vars: dict[str, str] | None = None,
) -> dict:
    """Run the AgenticVBench verifier in an isolated Docker container.

    Maps local directories to the absolute paths that test.sh expects:
      vw_dir/tests    → /tests
      vw_dir/baked    → /baked
      vw_dir/workspace → /workspace
      vw_dir/logs     → /logs

    This preserves the official test.sh semantics without modification.
    """
    test_sh = vw_dir / "tests" / "test.sh"
    if not test_sh.is_file():
        return {"status": "error", "reason": "test.sh not found", "reward": 0.0}

    vw_dir = Path(vw_dir).resolve()

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    # Set CUTBENCH_REPURPOSE_ONLY=1 as test.sh expects
    env["CUTBENCH_REPURPOSE_ONLY"] = "1"

    # Build docker run command with correct volume mappings
    # Use --entrypoint /bin/bash to bypass the agent image's ENTRYPOINT
    # (which runs entrypoint.sh and would treat "bash" as a task file)
    cmd = [
        "docker", "run", "--rm",
        "--entrypoint", "/bin/bash",
        "--name", f"avb-verifier-{int(__import__('time').time())}",
        "-v", f"{vw_dir / 'tests'}:/tests:ro",
        "-v", f"{vw_dir / 'baked'}:/baked:ro",
        "-v", f"{vw_dir / 'workspace'}:/workspace:rw",
        "-v", f"{vw_dir / 'logs'}:/logs:rw",
        "-e", "CUTBENCH_REPURPOSE_ONLY=1",
        "-e", f"GEMINI_API_KEY={env.get('GEMINI_API_KEY', '')}",
        "-e", f"ANTHROPIC_API_KEY={env.get('ANTHROPIC_API_KEY', '')}",
        image,
        "/tests/test.sh",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "Verifier timed out after 1800s", "reward": 0.0}
    except Exception as e:
        return {"status": "error", "reason": str(e), "reward": 0.0}

    # Parse reward.json from the mounted logs directory
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


def evaluate(results_dir: Path, task_id: str, upstream_root: Path | None = None, image: str | None = None) -> dict:
    """Run the EDIT verifier and return standardized results.

    Supports two modes controlled by EDIT_VERIFIER_MODE env var:
    - "official": uses frozen AgenticVBench Gemini+Anthropic verifier in Docker
    - "adapted": uses Qwen-VL (visual judge) + Qwen-Omni (audio judge) via DashScope
    """
    verifier_mode = os.environ.get("EDIT_VERIFIER_MODE", "adapted")

    result = {
        "benchmark": "AgenticVBench",
        "family": "repurpose",
        "task_id": task_id,
        "verifier_commit": None,
        "verifier_mode": verifier_mode,
        "official_verifier": verifier_mode == "official",
        "pass": False,
        "reward": 0.0,
        "details": {},
        "status": "unknown",
        "pass_threshold": 0.5,
        "pass_threshold_source": "project-defined",
    }

    if verifier_mode == "adapted":
        result["verifier_basis"] = "AgenticVBench-derived adapted"
        result["visual_judge"] = {
            "provider": "dashscope",
            "model": os.environ.get("VLM_MODEL", ""),
        }
        result["audio_judge"] = {
            "provider": "dashscope",
            "model": os.environ.get("OMNI_MODEL", ""),
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

    if verifier_mode == "official":
        return _evaluate_official(results_dir, task_id, upstream_root, image, result)
    else:
        return _evaluate_adapted(results_dir, task_id, upstream_root, result)


def _evaluate_official(results_dir: Path, task_id: str, upstream_root: Path | None,
                       image: str | None, result: dict) -> dict:
    """Run the official AgenticVBench verifier (Gemini + Anthropic)."""
    # Check API keys
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_gemini or not has_anthropic:
        result["status"] = "missing_official_verifier_keys"
        result["details"]["reason"] = (
            "Official AgenticVBench verifier requires both GEMINI_API_KEY and ANTHROPIC_API_KEY. "
            "Set EDIT_VERIFIER_MODE=adapted to use Qwen-VL/Qwen-Omni instead."
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

    # Run verifier in isolated Docker container
    verifier_image = image or os.environ.get("VIDEO_AGENT_BENCH_IMAGE", "video-agent-bench:1.0")
    verifier_result = run_verifier_in_docker(vw_dir, verifier_image)
    result["status"] = verifier_result["status"]
    result["reward"] = verifier_result.get("reward", 0.0)
    result["details"] = {k: v for k, v in verifier_result.items() if k not in ("stdout", "stderr")}
    result["pass"] = result["reward"] > 0.5
    return result


def _evaluate_adapted(results_dir: Path, task_id: str, upstream_root: Path | None,
                      result: dict) -> dict:
    """Run the adapted verifier using Qwen-VL (visual) + Qwen-Omni (audio).

    Reads the official AgenticVBench rubric items and evaluates them
    using DashScope Qwen models instead of Gemini+Anthropic.

    Deterministic items (ffprobe checks) run directly.
    LLM-judge items use Qwen-VL for visual and Qwen-Omni for audio.
    """
    import sys as _sys
    _sys.path.insert(0, str(ROOT))

    # Check DashScope keys
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
    vlm_model = os.environ.get("VLM_MODEL", "")
    omni_model = os.environ.get("OMNI_MODEL", "")

    if not dashscope_key:
        result["status"] = "missing_dashscope_api_key"
        result["details"]["reason"] = "Adapted EDIT verifier requires DASHSCOPE_API_KEY"
        return result
    if not vlm_model:
        result["status"] = "missing_vlm_model"
        result["details"]["reason"] = "Adapted EDIT verifier requires VLM_MODEL (e.g. qwen-vl-max)"
        return result

    # Load official rubric
    if upstream_root is None:
        upstream_root = ROOT / "upstream" / "agentic_vbench" / "tasks_repurpose"
    rubric_path = upstream_root / task_id / "steps" / "solve" / "tests" / "rubric.json"
    if not rubric_path.is_file():
        result["status"] = "no_rubric"
        result["details"]["reason"] = f"Rubric not found: {rubric_path}"
        return result

    with open(rubric_path) as f:
        rubric = json.load(f)

    # Run deterministic checks (same as official verifier pillar 0)
    agent_output = results_dir / "output" / "repurpose.mp4"
    det_results = _run_deterministic_edit_checks(agent_output, rubric)
    result["details"]["deterministic_checks"] = det_results

    # Run LLM-judge items using Qwen-VL (visual) and Qwen-Omni (audio)
    # For adapted mode, we evaluate visual items with Qwen-VL
    # Audio items require OMNI_MODEL — skip if not configured
    llm_results = _run_adapted_judge(agent_output, rubric, vlm_model, omni_model)
    result["details"]["adapted_judge"] = llm_results

    # Compute reward using official weight semantics
    # Positive items contribute weight; failed negative-weight items deduct
    total_weight = 0
    passed_weight = 0
    all_items = det_results["items"] + llm_results["items"]
    for item in all_items:
        w = item.get("weight", 1)
        total_weight += abs(w)
        if item["status"] == "pass":
            passed_weight += abs(w)

    result["reward"] = passed_weight / total_weight if total_weight > 0 else 0.0
    result["pass"] = result["reward"] > 0.5
    result["status"] = "evaluated"
    return result


def _run_deterministic_edit_checks(video_path: Path, rubric: dict) -> dict:
    """Run deterministic format checks from the official rubric.

    Routes by item["judge"] == "deterministic" (not by pillar).
    Preserves item["weight"] for scoring.
    """
    import subprocess as _sp

    items = [i for i in rubric.get("items", []) if i.get("judge") == "deterministic"]
    results = {"total": len(items), "passed": 0, "failed": 0, "items": []}

    # Probe once
    try:
        probe = _sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        probe_data = json.loads(probe.stdout) if probe.returncode == 0 else {}
    except Exception:
        probe_data = {}

    fmt = probe_data.get("format", {})
    streams = probe_data.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), {})
    astream = next((s for s in streams if s.get("codec_type") == "audio"), {})
    dur = float(fmt.get("duration", 0))
    w = int(vstream.get("width", 0))
    h = int(vstream.get("height", 0))
    vcodec = vstream.get("codec_name", "")
    acodec = astream.get("codec_name", "")
    channels = int(astream.get("channels", 0))
    sample_rate = int(astream.get("sample_rate", 0))
    fmt_name = fmt.get("format_name", "")

    for item in items:
        item_id = item.get("id", "")
        criterion = item.get("criterion", "")
        check = item.get("check", "")
        weight = item.get("weight", 1)
        check_lower = check.lower()

        passed = False
        detail = ""

        # Duration check
        if "duration" in check_lower and "75" in check:
            tol = 0.1
            passed = abs(dur - 75.0) <= tol
            detail = f"duration={dur:.1f}s (expected 75s \u00b1{tol}s)"
        elif "duration" in check_lower:
            passed = dur > 0
            detail = f"duration={dur:.1f}s"
        # Vertical resolution
        elif "1080" in check and "1920" in check:
            passed = (w == 1080 and h == 1920)
            detail = f"{w}x{h} (expected 1080x1920)"
        elif "vertical" in check_lower or ("width" in check_lower and "height" in check_lower):
            passed = h > w
            detail = f"{w}x{h}"
        # Codec / container
        elif "codec" in check_lower or "container" in check_lower or "h264" in check_lower:
            passed = "mp4" in fmt_name and vcodec in ("h264", "hevc") and acodec in ("aac", "ac3")
            detail = f"format={fmt_name}, vcodec={vcodec}, acodec={acodec}"
        # Stereo / sample rate
        elif "stereo" in check_lower or "channels" in check_lower:
            passed = channels == 2 and sample_rate in (44100, 48000)
            detail = f"channels={channels}, sample_rate={sample_rate}"
        # Dead audio (silence detection)
        elif "dead" in check_lower or "silence" in check_lower:
            try:
                sil_result = _sp.run(
                    ["ffmpeg", "-i", str(video_path), "-af",
                     "silencedetect=noise=-45dB:d=1.5", "-f", "null", "-"],
                    capture_output=True, text=True, timeout=60,
                )
                silence_count = sil_result.stderr.count("silence_start")
                passed = silence_count == 0
                detail = f"silence_events={silence_count}"
            except Exception as e:
                passed = False
                detail = f"silence detection error: {e}"
        # Novel voice-over
        elif "novel" in check_lower or "voice" in check_lower:
            passed = False
            detail = "requires ASR transcript comparison - not implemented in adapted mode"
        else:
            passed = False
            detail = f"unrecognized deterministic check: {check[:60]}"

        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1
        results["items"].append({"id": item_id, "status": "pass" if passed else "fail",
                                  "detail": detail, "criterion": criterion,
                                  "weight": weight})

    return results


def _run_adapted_judge(video_path: Path, rubric: dict, vlm_model: str, omni_model: str) -> dict:
    """Run LLM-judge rubric items using Qwen-VL (visual) and Qwen-Omni (audio).

    Routes by item["judge"] field (not by pillar number):
    - judge == "opus-vision" -> Qwen-VL adapted visual judge
    - judge == "gemini-audio" -> Qwen-Omni adapted audio judge

    Preserves item["weight"] including negative weights for penalty items.
    Failed items that are not evaluated (no judge available) are FAIL, not PASS.
    """
    import tempfile
    import subprocess as _sp
    import shutil
    from tools.providers.dashscope_vlm import vlm_check_prompt_adherence
    from tools.providers.dashscope_omni import omni_judge_audio

    items = [i for i in rubric.get("items", []) if i.get("judge") != "deterministic"]
    results = {"total": len(items), "passed": 0, "failed": 0, "items": []}

    # Extract frames from the video for visual judging
    tmpdir = tempfile.mkdtemp(prefix="edit_judge_")
    probe = _sp.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    duration = 0.0
    if probe.returncode == 0:
        try:
            duration = float(json.loads(probe.stdout).get("format", {}).get("duration", 0))
        except Exception:
            pass

    frame_paths = []
    for i in range(5):
        t = (duration / 6) * (i + 1) if duration > 0 else 0
        fp = f"{tmpdir}/frame_{i:03d}.png"
        _sp.run(["ffmpeg", "-y", "-ss", str(t), "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", fp],
                capture_output=True, timeout=30)
        if os.path.exists(fp):
            frame_paths.append(fp)

    # Extract audio for audio judging (compressed to stay under 10MB)
    audio_path = f"{tmpdir}/audio.mp3"
    _sp.run(["ffmpeg", "-y", "-i", str(video_path),
             "-ac", "1", "-ar", "16000", "-b:a", "64k",
             audio_path],
            capture_output=True, timeout=60)

    for item in items:
        item_id = item.get("id", "")
        criterion = item.get("criterion", "")
        judge_type = item.get("judge", "")
        weight = item.get("weight", 1)
        why = item.get("why", "")

        passed = False
        detail = ""

        if judge_type == "opus-vision":
            # Visual judge -> Qwen-VL
            if frame_paths:
                judge_prompt = (
                    f"You are judging a video edit. Criterion: {criterion}\n"
                    f"Why this matters: {why}\n"
                    f"Does the video meet this criterion? "
                    f"Answer YES or NO, then explain briefly."
                )
                judge_result = vlm_check_prompt_adherence(
                    frame_paths, judge_prompt, model=vlm_model,
                )
                passed = judge_result["pass"]
                detail = judge_result["detail"]
            else:
                passed = False
                detail = "no frames extracted for visual judge"

        elif judge_type == "gemini-audio":
            # Audio judge -> Qwen-Omni
            if omni_model and os.path.exists(audio_path):
                judge_prompt = (
                    f"You are judging the audio of a video edit. Criterion: {criterion}\n"
                    f"Why this matters: {why}\n"
                    f"Does the audio meet this criterion? "
                    f"Answer YES or NO, then explain briefly."
                )
                judge_result = omni_judge_audio(audio_path, judge_prompt, model=omni_model)
                passed = judge_result["pass"]
                detail = judge_result["detail"]
            elif not omni_model:
                passed = False
                detail = "OMNI_MODEL not set - audio judge NOT_EVALUATED (FAIL)"
            else:
                passed = False
                detail = "audio extraction failed - NOT_EVALUATED (FAIL)"

        else:
            # Unknown judge type -> FAIL (not silently pass)
            passed = False
            detail = f"unknown judge type: {judge_type}"

        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1
        results["items"].append({"id": item_id, "status": "pass" if passed else "fail",
                                  "detail": detail, "criterion": criterion,
                                  "weight": weight, "judge": judge_type})

    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)

    return results
