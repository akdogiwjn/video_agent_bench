#!/usr/bin/env python3
"""GEN Verifier: Multi-benchmark-derived evaluation adapter.

GEN cases are multi-benchmark-derived (VBench prompt + VideoWeaver agentic
pattern). The verifier combines:

1. Case-specific deterministic rubric (project-defined, based on VBench +
   VideoWeaver evaluation dimensions) — always runs
2. VideoWeaver Process Evaluation (if AutomaticSkillOptimization/ is available)
3. VideoWeaver Output Evaluation (if AutomaticSkillOptimization/ is available)

The rubric_source is always "project-defined" — we do NOT claim to use
official VideoWeaver or VBench rubrics.

Usage:
    python3 verifier/gen/evaluate.py --results <run-dir> [--case-dir <path>]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def find_case_rubric(case_dir: Path) -> dict | None:
    """Locate and load the case-specific rubric."""
    rubric_path = case_dir / "rubric" / "rubric_deterministic.json"
    if rubric_path.is_file():
        with open(rubric_path) as f:
            return json.load(f)
    return None


def find_video_weaver_eval(upstream_root: Path | None = None) -> dict:
    """Locate VideoWeaver evaluation code in the upstream freeze.

    The evaluation code (evaluation_PRM, evaluation_ORM) lives in
    AutomaticSkillOptimization/ which was NOT frozen in Milestone 1.
    Only skills/ were frozen. This is optional — the case-specific
    deterministic rubric runs regardless.
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
            "VideoWeaver Process/Output evaluation code (AutomaticSkillOptimization/) "
            "was not frozen. Only the case-specific deterministic rubric runs. "
            "Fetch AutomaticSkillOptimization/ from VideoWeaver upstream to enable "
            "additional process/output evaluation."
        ),
    }


def run_deterministic_checks(results_dir: Path, rubric: dict) -> dict:
    """Run deterministic format and process checks from the case rubric.

    These checks use ffprobe and file inspection — they do NOT require
    any LLM or external API.
    """
    items = rubric.get("items", [])
    results = {
        "total_items": len(items),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "items": [],
    }

    output_dir = results_dir / "output"
    final_mp4 = output_dir / "final.mp4"

    for item in items:
        item_id = item.get("id", "unknown")
        judge = item.get("judge", "deterministic")
        criterion = item.get("criterion", "")
        check_desc = item.get("check", "")

        # Skip non-deterministic items
        if judge not in ("deterministic", "deterministic_optional"):
            results["skipped"] += 1
            results["items"].append({
                "id": item_id,
                "status": "skipped",
                "judge": judge,
                "criterion": criterion,
            })
            continue

        passed = False
        detail = ""

        # F-01: file exists
        if "file_exists" in check_desc or "exists" in criterion.lower():
            passed = final_mp4.is_file()
            detail = f"final.mp4 exists: {passed}"

        # F-02: MP4 + H.264
        elif "h264" in check_desc.lower() or "codec" in criterion.lower():
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
        elif "resolution" in check_desc.lower() or "1280" in check_desc:
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
        elif "duration" in check_desc.lower() or "15" in check_desc:
            if final_mp4.is_file():
                probe = probe_video(final_mp4)
                dur = float(probe.get("format", {}).get("duration", 0))
                passed = 15.0 <= dur <= 30.0
                detail = f"duration={dur:.1f}s"
            else:
                detail = "final.mp4 not found"

        # P-01: intermediate artifacts
        elif "intermediate" in criterion.lower():
            ws_output = results_dir / "workspace" / "output"
            if ws_output.is_dir():
                files = [f for f in ws_output.iterdir() if f.is_file() and f.name != "final.mp4" and f.name != ".DS_Store"]
                passed = len(files) > 0
                detail = f"{len(files)} intermediate files found"
            else:
                detail = "no workspace/output directory"

        # P-02: tool calls in trajectory
        elif "tool_call" in check_desc.lower() or "trajectory" in check_desc.lower():
            traj_path = results_dir / "agent" / "normalized_trajectory.json"
            if not traj_path.is_file():
                traj_path = results_dir / "agent" / "trajectory.json"
            if traj_path.is_file():
                try:
                    with open(traj_path) as f:
                        traj = json.load(f)
                    if isinstance(traj, list):
                        tool_calls = sum(1 for e in traj if isinstance(e, dict) and e.get("type") == "tool_call")
                        passed = tool_calls > 0
                        detail = f"{tool_calls} tool calls found"
                    else:
                        detail = "trajectory is not a list"
                except Exception as e:
                    detail = f"parse error: {e}"
            else:
                detail = "trajectory.json not found"

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
            "judge": judge,
            "criterion": criterion,
            "detail": detail,
        })

    total_scoreable = results["passed"] + results["failed"]
    results["pass_rate"] = results["passed"] / total_scoreable if total_scoreable > 0 else 0.0

    return results


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


def evaluate(results_dir: Path, case_dir: Path | None = None) -> dict:
    """Run the GEN verifier and return standardized results."""
    result = {
        "benchmark": "multi-benchmark-derived",
        "case_id": None,
        "rubric_source": "project-defined",
        "rubric_basis": ["VBench", "VideoWeaver"],
        "official_videoweaver_rubric": False,
        "verifier_commit": None,
        "pass": False,
        "reward": 0.0,
        "details": {},
        "status": "unknown",
    }

    # Locate case rubric
    if case_dir is None:
        case_dir = ROOT / "cases" / "gen" / "gen_case_001"

    rubric = find_case_rubric(case_dir)
    if rubric is None:
        result["status"] = "no_rubric"
        result["details"]["reason"] = f"No rubric found in {case_dir}"
        return result

    result["case_id"] = rubric.get("case_id", "unknown")
    result["details"]["rubric_source"] = rubric.get("rubric_source", "project-defined")
    result["details"]["rubric_basis"] = rubric.get("rubric_basis", [])

    # 1. Run deterministic checks (always)
    det_results = run_deterministic_checks(results_dir, rubric)
    result["details"]["deterministic_checks"] = det_results

    # 2. Check VideoWeaver eval availability (optional)
    eval_info = find_video_weaver_eval()
    result["details"]["videoweaver_eval"] = {
        "available": eval_info["available"],
        "note": eval_info["note"],
    }

    if eval_info["available"]:
        # Run VideoWeaver PRM/ORM if available (optional enhancement)
        result["details"]["videoweaver_eval"]["note"] = "VideoWeaver eval code available but not yet integrated."
    else:
        result["details"]["videoweaver_eval"]["note"] = eval_info["note"]

    # Compute reward from deterministic checks
    scoring = rubric.get("scoring", {})
    format_weight = scoring.get("format_weight", 0.4)
    content_weight = scoring.get("content_weight", 0.3)
    process_weight = scoring.get("process_weight", 0.3)

    # Compute pillar pass rates
    format_items = [i for i in det_results["items"] if "format" in i.get("criterion", "").lower() or i["id"].startswith("F-")]
    content_items = [i for i in det_results["items"] if "content" in i.get("criterion", "").lower() or i["id"].startswith("C-")]
    process_items = [i for i in det_results["items"] if "process" in i.get("criterion", "").lower() or i["id"].startswith("P-")]

    def pass_rate(items):
        scored = [i for i in items if i["status"] in ("pass", "fail")]
        if not scored:
            return 0.0
        return sum(1 for i in scored if i["status"] == "pass") / len(scored)

    format_rate = pass_rate(format_items)
    content_rate = pass_rate(content_items)
    process_rate = pass_rate(process_items)

    result["reward"] = format_weight * format_rate + content_weight * content_rate + process_weight * process_rate
    result["pass"] = result["reward"] > 0.5
    result["status"] = "evaluated"
    result["details"]["pillar_scores"] = {
        "format": format_rate,
        "content": content_rate,
        "process": process_rate,
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="GEN verifier (multi-benchmark-derived)")
    parser.add_argument("--results", required=True, help="Path to results/<run-id>/ directory")
    parser.add_argument("--case-dir", default=None, help="Path to the case directory (default: cases/gen/gen_case_001)")
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
    print(f"  rubric:     {result.get('rubric_source', 'unknown')}")
    if result["status"] != "evaluated":
        print(f"  reason:     {result['details'].get('reason', 'unknown')}")
    print(f"  output:     {output_path}")

    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
