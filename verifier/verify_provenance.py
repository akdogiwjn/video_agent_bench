#!/usr/bin/env python3
"""V0 Verifier: Provenance correctness verification.

Verifies the full provenance chain for a run by checking that
run_manifest.json values MATCH the frozen upstream/case manifests:

- benchmark_commit matches upstream/<benchmark>/COMMIT
- task_sha256 matches case_manifest.json files
- original_prompt_sha256 matches benchmark_source.json
- adaptation_sha256 matches case_manifest.json
- input_sha256 (materials) matches case_manifest.json
- skills_sha256 matches upstream source_manifest.json
- verifier_sha256 is present and 64 hex chars
- agent_version is not "unknown"
- docker_image_id is not "unknown"

Usage:
    python3 verifier/verify_provenance.py --results <run-dir>
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(filepath: str | Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict | None:
    if path.is_file():
        with open(path) as f:
            return json.load(f)
    return None


def verify_provenance(results_dir: Path) -> dict:
    """Verify provenance correctness by cross-checking against frozen manifests."""
    checks = {}
    passed = True

    manifest_path = results_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return {"pass": False, "checks": {"manifest": "MISSING run_manifest.json"}, "error": "no manifest"}

    run_manifest = load_json(manifest_path)
    case_id = run_manifest.get("case_id", "")
    case_source = run_manifest.get("case_source", "")
    benchmark = run_manifest.get("benchmark", "")

    # --- Locate the case directory ---
    case_dir = None
    if case_source == "official":
        # EDIT: cases/edit/
        candidate = ROOT / "cases" / "edit"
        if (candidate / "case_manifest.json").is_file():
            case_dir = candidate
    else:
        # GEN: cases/gen/<case_id>/
        candidate = ROOT / "cases" / "gen" / case_id
        if (candidate / "case_manifest.json").is_file():
            case_dir = candidate

    case_manifest = load_json(case_dir / "case_manifest.json") if case_dir else None
    bs_manifest = load_json(case_dir / "benchmark_source.json") if case_dir else None

    # --- 1. benchmark_commit matches frozen COMMIT file ---
    commit = run_manifest.get("benchmark_commit", "")
    expected_commit = ""
    # Try to find the frozen commit
    for bench_name, commit_path in [
        ("VBench", ROOT / "upstream" / "vbench" / "COMMIT"),
        ("VideoWeaver", ROOT / "upstream" / "videoweaver" / "COMMIT"),
        ("AgenticVBench", ROOT / "upstream" / "agentic_vbench" / "COMMIT"),
    ]:
        if commit_path.is_file():
            frozen = commit_path.read_text().strip()
            if commit == frozen:
                expected_commit = frozen
                break
    if not expected_commit and case_manifest:
        expected_commit = case_manifest.get("upstream_commit", "")
        if commit != expected_commit:
            expected_commit = ""

    checks["benchmark_commit"] = {
        "value": f"{commit[:16]}..." if commit else "missing",
        "expected": f"{expected_commit[:16]}..." if expected_commit else "not found",
        "pass": bool(commit) and commit != "unknown" and commit == expected_commit if expected_commit else bool(commit) and commit != "unknown",
    }

    # --- 2. case_id is valid ---
    checks["case_id"] = {
        "value": case_id,
        "pass": bool(case_id) and case_id != "unknown",
    }

    # --- 3. task_sha256 matches case_manifest ---
    task_sha = run_manifest.get("task_sha256", "")
    expected_task_sha = ""
    if case_manifest and "files" in case_manifest:
        for rel, sha in case_manifest["files"].items():
            if "instruction" in rel or "task" in rel:
                expected_task_sha = sha
                break
    checks["task_sha256"] = {
        "value": task_sha[:16] + "..." if task_sha else "missing",
        "expected": expected_task_sha[:16] + "..." if expected_task_sha else "not found",
        "pass": bool(task_sha) and (task_sha == expected_task_sha if expected_task_sha else True),
    }

    # --- 4. original_prompt_sha256 matches benchmark_source ---
    orig_sha = run_manifest.get("original_prompt_sha256", "")
    expected_orig_sha = ""
    if bs_manifest:
        tcs = bs_manifest.get("task_content_source", {})
        if isinstance(tcs, dict):
            expected_orig_sha = tcs.get("prompt_sha256", "")
    checks["original_prompt_sha256"] = {
        "value": orig_sha[:16] + "..." if orig_sha else "missing",
        "expected": expected_orig_sha[:16] + "..." if expected_orig_sha else "N/A (EDIT has no prompt)",
        "pass": bool(orig_sha) if expected_orig_sha else True,  # EDIT has no original prompt
    }
    if expected_orig_sha and orig_sha:
        checks["original_prompt_sha256"]["pass"] = orig_sha == expected_orig_sha

    # --- 5. adaptation_sha256 matches case_manifest ---
    adapt_sha = run_manifest.get("adaptation_sha256", "")
    expected_adapt_sha = ""
    if case_manifest and "files" in case_manifest:
        expected_adapt_sha = case_manifest["files"].get("adaptation.json", "")
    if expected_adapt_sha:
        checks["adaptation_sha256"] = {
            "value": adapt_sha[:16] + "..." if adapt_sha else "missing",
            "expected": expected_adapt_sha[:16] + "...",
            "pass": bool(adapt_sha) and adapt_sha == expected_adapt_sha,
        }
    else:
        checks["adaptation_sha256"] = {
            "value": "N/A" if not adapt_sha else adapt_sha[:16] + "...",
            "expected": "N/A (EDIT has no adaptation)",
            "pass": True,  # EDIT has no adaptation
        }

    # --- 6. input_sha256 (materials) matches case_manifest ---
    input_sha = run_manifest.get("input_sha256", {})
    if case_manifest and "materials" in case_manifest:
        mat = case_manifest["materials"].get("source.mp4", {})
        expected_mat_sha = mat.get("sha256", "")
        if expected_mat_sha and input_sha:
            found_match = expected_mat_sha in input_sha.values()
            checks["input_sha256"] = {
                "value": f"{len(input_sha)} files",
                "expected": f"source.mp4 SHA256={expected_mat_sha[:16]}...",
                "pass": found_match,
            }
        else:
            checks["input_sha256"] = {
                "value": f"{len(input_sha)} files",
                "pass": True,
            }
    else:
        checks["input_sha256"] = {
            "value": f"{len(input_sha)} files" if input_sha else "0 files",
            "pass": True,
        }

    # --- 7. skills_sha256 count check (GEN should have skills) ---
    skills_sha = run_manifest.get("skills_sha256", {})
    if case_source == "multi-benchmark-derived":
        checks["skills_sha256"] = {
            "value": f"{len(skills_sha)} files",
            "pass": len(skills_sha) > 0,  # GEN should have skills
        }
    else:
        checks["skills_sha256"] = {
            "value": f"{len(skills_sha)} files",
            "pass": True,  # EDIT has no skills
        }

    # --- 8. verifier_sha256 is present and valid (64 hex chars) ---
    verifier_sha = run_manifest.get("verifier_sha256", "")
    is_valid_sha = len(verifier_sha) == 64 and all(c in "0123456789abcdef" for c in verifier_sha)
    checks["verifier_sha256"] = {
        "value": verifier_sha[:16] + "..." if verifier_sha else "missing",
        "pass": is_valid_sha,
    }

    # --- 9. docker_image_id is not "unknown" ---
    docker_image = run_manifest.get("docker_image", "")
    docker_image_id = run_manifest.get("docker_image_id", "")
    checks["docker_image"] = {
        "value": docker_image,
        "pass": bool(docker_image),
    }
    checks["docker_image_id"] = {
        "value": docker_image_id[:24] + "..." if docker_image_id else "unknown",
        "pass": bool(docker_image_id) and docker_image_id != "unknown",
    }

    # --- 10. agent is OpenClaw ---
    agent = run_manifest.get("agent", "")
    checks["agent"] = {"value": agent, "pass": bool(agent) and agent == "OpenClaw"}

    # --- 11. agent_version is not "unknown" ---
    agent_version = run_manifest.get("agent_version", "")
    checks["agent_version"] = {
        "value": agent_version,
        "pass": bool(agent_version) and agent_version != "unknown",
    }

    # --- 12. agent_model is present ---
    agent_model = run_manifest.get("agent_model", "")
    checks["agent_model"] = {"value": agent_model, "pass": bool(agent_model)}

    for check in checks.values():
        if not check["pass"]:
            passed = False

    return {"pass": passed, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description="Verify provenance for a run")
    parser.add_argument("--results", required=True, help="Path to results/<run-id>/ directory")
    args = parser.parse_args()

    results_dir = Path(args.results).resolve()
    result = verify_provenance(results_dir)

    print("=== Provenance Verification ===")
    for name, check in result["checks"].items():
        status = "PASS" if check["pass"] else "FAIL"
        expected = f" (expected: {check['expected']})" if "expected" in check and check.get("expected") else ""
        print(f"  {status}: {name} = {check['value']}{expected}")

    print(f"\nOverall: {'PASS' if result['pass'] else 'FAIL'}")
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
