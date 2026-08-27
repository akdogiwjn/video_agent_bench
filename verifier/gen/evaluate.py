#!/usr/bin/env python3
"""GEN Verifier: Multi-benchmark-derived evaluation adapter.

Hard gate design (revised):
- format_pass = ALL F-* checks pass
- semantic_pass = C-01 VLM prompt adherence check passes (VLM unavailable = FAIL)
- shot_diversity_pass = C-02 multiple distinct shots check passes
- process_pass = P-* checks pass (>=2 tool calls, >=2 intermediates)
- Overall pass = format_pass AND semantic_pass AND shot_diversity_pass AND process_pass

C-01 is the real semantic gate: it checks whether the video content
matches the original VBench prompt. If a VLM API key is available, it
uses VLM-based prompt adherence. If not, it uses prompt-specific color
analysis (e.g., sunset scenes should have warm colors). Either way,
C-01 is NEVER skipped — a SMPTE test pattern will FAIL.

Usage:
    python3 verifier/gen/evaluate.py --results <run-dir> [--case-dir <path>]
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def find_case_rubric(case_dir: Path) -> dict | None:
    """Locate and load the case-specific rubric."""
    rubric_path = case_dir / "rubric" / "rubric_deterministic.json"
    if rubric_path.is_file():
        with open(rubric_path) as f:
            return json.load(f)
    return None


def find_original_prompt(case_dir: Path) -> str:
    """Load the original VBench prompt for semantic comparison."""
    prompt_path = case_dir / "source" / "original_prompt.txt"
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8").strip()
    return ""


def probe_video(filepath: Path) -> dict:
    """Run ffprobe on a video file."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(filepath)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return {}


def extract_frames(video_path: Path, num_frames: int = 10) -> list[str]:
    """Extract evenly-spaced frames from the video for analysis.

    Returns paths to temporary PNG files. The caller should clean up
    the temp directory after use by calling cleanup_frames().
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="gen_verify_"))
    probe = probe_video(video_path)
    duration = float(probe.get("format", {}).get("duration", 0))
    if duration <= 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return []

    frames = []
    for i in range(num_frames):
        t = (duration / (num_frames + 1)) * (i + 1)
        frame_path = tmpdir / f"frame_{i:03d}.png"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(t), "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", str(frame_path)],
                capture_output=True, timeout=30,
            )
            if frame_path.is_file():
                frames.append(str(frame_path))
        except Exception:
            pass
    if not frames:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return frames


def cleanup_frames(frame_paths: list[str]):
    """Clean up temporary frame files and their parent directory."""
    if not frame_paths:
        return
    try:
        tmpdir = Path(frame_paths[0]).parent
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


def vlm_check_prompt_adherence(frame_paths: list[str], prompt: str) -> dict:
    """Use a VLM to check if the video frames match the prompt.

    Returns {"pass": bool, "detail": str, "method": "vlm"}.
    If no VLM API key is available, returns {"pass": False, ...} so
    color analysis is diagnostic only (never a PASS gate).
    """
    # Use DashScope API key and VLM model (Qwen-VL)
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key or not frame_paths:
        return {"pass": False, "detail": "no DASHSCOPE_API_KEY or no frames", "method": "vlm_unavailable"}

    vlm_model = os.environ.get("VLM_MODEL", "")
    if not vlm_model:
        return {"pass": False, "detail": "VLM_MODEL not set", "method": "vlm_unavailable"}

    try:
        from openai import OpenAI
    except ImportError:
        return {"pass": False, "detail": "openai package not installed", "method": "vlm_unavailable"}

    base_url = os.environ.get("VLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    client = OpenAI(api_key=api_key, base_url=base_url)

    # Use first, middle, and last frames
    sample_indices = [0, len(frame_paths) // 2, -1] if len(frame_paths) >= 3 else [0]
    sample_frames = [frame_paths[i] for i in sample_indices]

    vlm_prompt = (
        f"The following is a video generation prompt:\n\n\"{prompt}\"\n\n"
        f"I will show you {len(sample_frames)} frames from a generated video. "
        f"Does the visual content of these frames match the prompt? "
        f"Answer with EXACTLY 'YES' or 'NO' on the first line, then a one-sentence reason."
    )

    content = [{"type": "text", "text": vlm_prompt}]
    for fp in sample_frames:
        with open(fp, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })

    try:
        response = client.chat.completions.create(
            model=vlm_model,
            messages=[{"role": "user", "content": content}],
            max_tokens=200,
        )
        answer = response.choices[0].message.content.strip()
        is_yes = answer.upper().startswith("YES")
        return {"pass": is_yes, "detail": f"VLM answer: {answer}", "method": "vlm"}
    except Exception as e:
        return {"pass": False, "detail": f"VLM error: {e}", "method": "vlm_error"}


def color_analysis_check(frame_paths: list[str], prompt: str) -> dict:
    """Prompt-specific color analysis for semantic content checking.

    This is a fallback when no VLM is available. It checks whether the
    video frames have color characteristics consistent with the prompt.

    For sunset/sky prompts: checks for warm colors (orange, red, purple,
    yellow) and brightness gradients.

    For other prompts: checks that frames are not monochrome and have
    reasonable color diversity.

    Returns {"pass": bool, "detail": str, "method": "color_analysis"}.
    """
    if not frame_paths:
        return {"pass": False, "detail": "no frames extracted", "method": "color_analysis"}

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return {"pass": False, "detail": "numpy/PIL not available", "method": "color_analysis"}

    pixel_data = []
    for fp in frame_paths:
        try:
            img = Image.open(fp).convert("RGB")
            arr = np.array(img)
            pixel_data.append(arr)
        except Exception:
            pass

    if not pixel_data:
        return {"pass": False, "detail": "could not read frames", "method": "color_analysis"}

    prompt_lower = prompt.lower()

    # Check for black/solid color
    first_frame = pixel_data[0]
    mean_brightness = float(first_frame.mean())
    std_brightness = float(first_frame.std())
    is_black = mean_brightness < 10
    is_solid = std_brightness < 5

    if is_black or is_solid:
        return {"pass": False, "detail": f"black_or_solid (brightness={mean_brightness:.1f}, std={std_brightness:.1f})",
                "method": "color_analysis"}

    # Check for motion (variation between frames)
    if len(pixel_data) >= 2:
        frame_diffs = []
        for i in range(1, len(pixel_data)):
            diff = float(np.abs(pixel_data[i].astype(float) - pixel_data[0].astype(float)).mean())
            frame_diffs.append(diff)
        avg_diff = sum(frame_diffs) / len(frame_diffs) if frame_diffs else 0.0
    else:
        avg_diff = 0.0

    if avg_diff < 2.0:
        return {"pass": False, "detail": f"no motion (avg_frame_diff={avg_diff:.2f})", "method": "color_analysis"}

    # Prompt-specific color checks
    # Sunset/sky prompt: check for warm colors
    if "sunset" in prompt_lower or "sky" in prompt_lower or "horizon" in prompt_lower:
        warm_pixel_count = 0
        total_pixels = 0
        for arr in pixel_data:
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            # Warm colors: R > G > B with R > 80
            warm_mask = (r > g) & (g > b) & (r > 80)
            warm_pixel_count += int(warm_mask.sum())
            total_pixels += arr.shape[0] * arr.shape[1]
        warm_ratio = warm_pixel_count / total_pixels if total_pixels > 0 else 0.0

        if warm_ratio < 0.10:
            return {"pass": False,
                    "detail": f"sunset prompt but warm_color_ratio={warm_ratio:.3f} (threshold=0.10)",
                    "method": "color_analysis"}

        return {"pass": True,
                "detail": f"warm_color_ratio={warm_ratio:.3f}, motion={avg_diff:.2f}, brightness={mean_brightness:.1f}",
                "method": "color_analysis"}

    # Generic: check color diversity
    color_diversity = float(std_brightness) / 128.0
    if color_diversity < 0.15:
        return {"pass": False, "detail": f"low color diversity (std/128={color_diversity:.3f})",
                "method": "color_analysis"}

    return {"pass": True,
            "detail": f"color_diversity={color_diversity:.3f}, motion={avg_diff:.2f}",
            "method": "color_analysis"}


def check_semantic_content(video_path: Path, prompt: str) -> dict:
    """Check if video content matches the prompt.

    Uses VLM-based prompt adherence. If VLM is unavailable, returns FAIL
    (NOT_EVALUATED). Color analysis is used only as a diagnostic signal
    in the detail, never as a PASS gate.

    This ensures that unrelated synthetic videos (e.g. SMPTE test patterns)
    cannot PASS the semantic gate without a real VLM confirming prompt
    adherence.
    """
    frames = extract_frames(video_path, num_frames=10)

    # Try VLM first
    vlm_result = vlm_check_prompt_adherence(frames, prompt)

    if vlm_result["method"] == "vlm":
        # VLM gave a definitive answer — use it as the semantic gate
        cleanup_frames(frames)
        return vlm_result

    # VLM unavailable or errored — semantic gate FAILS
    # Color analysis is included as diagnostic only, NOT as a pass gate
    color_diag = color_analysis_check(frames, prompt)
    cleanup_frames(frames)
    return {
        "pass": False,
        "detail": f"VLM unavailable — semantic check NOT_EVALUATED (FAIL). "
                  f"Color diagnostic: {color_diag['detail']}",
        "method": "vlm_unavailable_fail",
        "color_diagnostic": color_diag,
    }


def count_intermediate_artifacts(results_dir: Path, expected_output: str = "final.mp4") -> list[str]:
    """Recursively find intermediate artifacts in workspace/output.

    VideoWeaver creates nested directories like:
    output/<session_key>/videos/clip01.mp4
    output/<session_key>/images/key.png

    This function uses rglob to find ALL files, not just top-level.
    """
    ws_output = results_dir / "workspace" / "output"
    if not ws_output.is_dir():
        return []

    intermediates = []
    for f in ws_output.rglob("*"):
        if f.is_file() and f.name != expected_output and f.name != ".DS_Store":
            intermediates.append(str(f.relative_to(ws_output)))
    return intermediates


def count_tool_calls(results_dir: Path) -> int:
    """Count tool_call entries in trajectory.

    Accepts both normalized (tool_call) and raw OpenClaw (tool.call) types.
    Reads from events.jsonl, normalized_trajectory.json, or trajectory.json.
    """
    for traj_name in ["events.jsonl", "normalized_trajectory.json", "trajectory.json"]:
        traj_path = results_dir / "agent" / traj_name
        if not traj_path.is_file():
            continue
        try:
            with open(traj_path) as f:
                try:
                    traj = json.load(f)
                except json.JSONDecodeError:
                    f.seek(0)
                    traj = [json.loads(line) for line in f if line.strip()]
            if isinstance(traj, list):
                return sum(
                    1 for e in traj
                    if isinstance(e, dict) and e.get("type") in ("tool_call", "tool.call")
                )
        except Exception:
            pass
    return 0


def run_checks(results_dir: Path, rubric: dict, case_dir: Path) -> dict:
    """Run all checks and return detailed results."""
    output_dir = results_dir / "output"
    final_mp4 = output_dir / "final.mp4"
    original_prompt = find_original_prompt(case_dir)

    items = rubric.get("items", [])
    results = {
        "total_items": len(items),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "items": [],
    }

    for item in items:
        item_id = item.get("id", "unknown")
        judge = item.get("judge", "deterministic")
        criterion = item.get("criterion", "")
        check_desc = item.get("check", "")

        # NO MORE vlm_optional SKIP — everything runs
        passed = False
        detail = ""

        # F-01: file exists
        if item_id == "F-01" or "file_exists" in check_desc:
            passed = final_mp4.is_file()
            detail = f"final.mp4 exists: {passed}"

        # F-02: MP4 + H.264
        elif item_id == "F-02" or "h264" in check_desc.lower():
            if final_mp4.is_file():
                probe = probe_video(final_mp4)
                fmt = probe.get("format", {}).get("format_name", "")
                codec = ""
                for s in probe.get("streams", []):
                    if s.get("codec_type") == "video":
                        codec = s.get("codec_name", "")
                passed = "mp4" in fmt and codec == "h264"
                detail = f"format={fmt}, video_codec={codec}"
            else:
                detail = "final.mp4 not found"

        # F-03: resolution
        elif item_id == "F-03" or "resolution" in check_desc.lower():
            if final_mp4.is_file():
                probe = probe_video(final_mp4)
                for s in probe.get("streams", []):
                    if s.get("codec_type") == "video":
                        w = s.get("width", 0)
                        h = s.get("height", 0)
                        passed = w >= 1280 and h >= 720
                        detail = f"{w}x{h}"
                        break
            else:
                detail = "final.mp4 not found"

        # F-04: duration
        elif item_id == "F-04" or "duration" in check_desc.lower():
            if final_mp4.is_file():
                probe = probe_video(final_mp4)
                dur = float(probe.get("format", {}).get("duration", 0))
                passed = 15.0 <= dur <= 30.0
                detail = f"duration={dur:.1f}s"
            else:
                detail = "final.mp4 not found"

        # C-01: SEMANTIC content check (the real gate!)
        elif item_id == "C-01":
            if final_mp4.is_file() and original_prompt:
                sem_result = check_semantic_content(final_mp4, original_prompt)
                passed = sem_result["pass"]
                detail = f"method={sem_result['method']}, {sem_result['detail']}"
            elif not final_mp4.is_file():
                passed = False
                detail = "final.mp4 not found"
            else:
                passed = False
                detail = "original prompt not found — cannot do semantic check"

        # C-02: multiple distinct shots (scene detection)
        elif item_id == "C-02":
            if final_mp4.is_file():
                try:
                    result = subprocess.run(
                        ["scenedetect", "-i", str(final_mp4), "detect-content", "list-scenes"],
                        capture_output=True, text=True, timeout=60,
                    )
                    scene_count = result.stdout.count("Scene") // 2
                    passed = scene_count >= 2
                    detail = f"detected_scenes={scene_count}"
                except Exception:
                    # Fallback: frame analysis
                    frames = extract_frames(final_mp4, num_frames=15)
                    if len(frames) >= 2:
                        try:
                            import numpy as np
                            from PIL import Image
                            pixel_data = [np.array(Image.open(fp).convert("RGB")) for fp in frames]
                            diffs = [float(np.abs(pixel_data[i].astype(float) - pixel_data[0].astype(float)).mean())
                                     for i in range(1, len(pixel_data))]
                            avg_diff = sum(diffs) / len(diffs) if diffs else 0
                            passed = avg_diff > 5.0
                            detail = f"fallback: avg_frame_diff={avg_diff:.2f}"
                        except Exception:
                            passed = False
                            detail = "fallback analysis failed"
                    else:
                        passed = False
                        detail = "not enough frames for analysis"
            else:
                passed = False
                detail = "final.mp4 not found"

        # P-01: intermediate artifacts (recursive!)
        elif item_id == "P-01" or "intermediate" in criterion.lower():
            intermediates = count_intermediate_artifacts(results_dir)
            passed = len(intermediates) >= 2  # threshold raised to >=2
            detail = f"{len(intermediates)} intermediate files found (recursively)"

        # P-02: tool calls in trajectory (>=2 required)
        elif item_id == "P-02" or "tool_call" in check_desc.lower():
            tool_calls = count_tool_calls(results_dir)
            passed = tool_calls >= 2  # threshold raised to >=2
            detail = f"{tool_calls} tool calls found (threshold: >=2)"

        else:
            results["skipped"] += 1
            results["items"].append({
                "id": item_id,
                "status": "skipped",
                "judge": judge,
                "criterion": criterion,
                "reason": f"unrecognized check: {check_desc}",
            })
            continue

        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

        results["items"].append({
            "id": item_id,
            "status": "pass" if passed else "fail",
            "judge": "deterministic",
            "criterion": criterion,
            "detail": detail,
        })

    total_scoreable = results["passed"] + results["failed"]
    results["pass_rate"] = results["passed"] / total_scoreable if total_scoreable > 0 else 0.0
    return results


def evaluate(results_dir: Path, case_dir: Path | None = None) -> dict:
    """Run the GEN verifier and return standardized results.

    Hard gate design (revised):
    - format_pass = ALL F-* checks pass (rate == 1.0)
    - semantic_pass = C-01 VLM check passes (VLM unavailable = FAIL, color analysis is diagnostic only)
    - shot_diversity_pass = C-02 passes
    - process_pass = ALL P-* checks pass (>=2 tool calls, >=2 intermediates)
    - Overall pass = format_pass AND semantic_pass AND shot_diversity_pass AND process_pass
    """
    result = {
        "benchmark": "multi-benchmark-derived",
        "case_id": None,
        "rubric_source": "project-defined",
        "rubric_basis": ["VBench", "VideoWeaver"],
        "official_videoweaver_rubric": False,
        "verifier_commit": "",
        "pass": False,
        "reward": 0.0,
        "details": {},
        "status": "unknown",
    }

    if case_dir is None:
        case_dir = ROOT / "cases" / "gen" / "gen_case_001"

    rubric = find_case_rubric(case_dir)
    if rubric is None:
        result["status"] = "no_rubric"
        result["details"]["reason"] = f"No rubric found in {case_dir}"
        return result

    result["case_id"] = rubric.get("case_id", "unknown")

    # Run all checks
    det_results = run_checks(results_dir, rubric, case_dir)
    result["details"]["checks"] = det_results

    # Check VideoWeaver eval availability (optional)
    eval_info = find_video_weaver_eval()
    result["details"]["videoweaver_eval"] = {
        "available": eval_info["available"],
        "note": eval_info["note"],
    }

    # Compute pillar pass rates
    format_items = [i for i in det_results["items"] if i["id"].startswith("F-")]
    semantic_items = [i for i in det_results["items"] if i["id"] == "C-01"]
    shot_items = [i for i in det_results["items"] if i["id"] == "C-02"]
    process_items = [i for i in det_results["items"] if i["id"].startswith("P-")]

    def all_pass(items):
        scored = [i for i in items if i["status"] in ("pass", "fail")]
        return len(scored) > 0 and all(i["status"] == "pass" for i in scored)

    format_pass = all_pass(format_items)
    semantic_pass = all_pass(semantic_items)
    shot_diversity_pass = all_pass(shot_items)
    process_pass = all_pass(process_items)

    result["details"]["hard_gates"] = {
        "format_pass": format_pass,
        "semantic_prompt_pass": semantic_pass,
        "shot_diversity_pass": shot_diversity_pass,
        "process_pass": process_pass,
    }

    # Scoring (informational only — pass requires all hard gates)
    total = det_results["passed"] + det_results["failed"]
    result["reward"] = det_results["passed"] / total if total > 0 else 0.0

    # PASS requires ALL hard gates
    result["pass"] = format_pass and semantic_pass and shot_diversity_pass and process_pass
    result["status"] = "evaluated"

    return result


def find_video_weaver_eval(upstream_root: Path | None = None) -> dict:
    """Locate VideoWeaver evaluation code in the upstream freeze."""
    if upstream_root is None:
        upstream_root = ROOT / "upstream" / "videoweaver"
    eval_prm = upstream_root / "AutomaticSkillOptimization" / "evaluation_PRM"
    eval_orm = upstream_root / "AutomaticSkillOptimization" / "evaluation_ORM"
    return {
        "evaluation_PRM_path": str(eval_prm) if eval_prm.is_dir() else None,
        "evaluation_ORM_path": str(eval_orm) if eval_orm.is_dir() else None,
        "available": eval_prm.is_dir() or eval_orm.is_dir(),
        "note": "VideoWeaver eval code not frozen. Only project-defined rubric runs." if not (eval_prm.is_dir() or eval_orm.is_dir()) else "Available",
    }


def main():
    parser = argparse.ArgumentParser(description="GEN verifier (multi-benchmark-derived)")
    parser.add_argument("--results", required=True, help="Path to results/<run-id>/ directory")
    parser.add_argument("--case-dir", default=None, help="Path to the case directory")
    args = parser.parse_args()

    results_dir = Path(args.results).resolve()
    case_dir = Path(args.case_dir) if args.case_dir else None

    result = evaluate(results_dir, case_dir)

    output_path = results_dir / "verification" / "verification_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"=== GEN Verification ===")
    print(f"  case_id:    {result.get('case_id', 'unknown')}")
    print(f"  status:     {result['status']}")
    print(f"  reward:     {result['reward']:.2f}")
    print(f"  pass:       {result['pass']}")
    gates = result.get("details", {}).get("hard_gates", {})
    for gate_name, gate_val in gates.items():
        print(f"  gate {gate_name}: {'PASS' if gate_val else 'FAIL'}")
    for item in result.get("details", {}).get("checks", {}).get("items", []):
        print(f"  {item['status'].upper()}: {item['id']} — {item.get('detail', '')}")
    print(f"  output:     {output_path}")

    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
