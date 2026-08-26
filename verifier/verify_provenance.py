#!/usr/bin/env python3
"""V0 Verifier: Provenance check.

Verifies the full provenance chain for a run:
- Benchmark commit
- Case ID
- Task SHA256
- Reference SHA
- Material SHA
- Skill SHA
- Docker image digest
- OpenClaw version

Usage:
    python3 verifier/verify_provenance.py --results <run-dir>
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def verify_provenance(results_dir: Path) -> dict:
    """Check provenance chain from run_manifest.json."""
    manifest_path = results_dir / "run_manifest.json"
    checks = {}
    passed = True

    if not manifest_path.is_file():
        return {"pass": False, "checks": {"manifest": "MISSING run_manifest.json"}, "error": "no manifest"}

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Benchmark commit
    commit = manifest.get("benchmark_commit", "")
    checks["benchmark_commit"] = {"value": commit, "pass": bool(commit) and commit != "unknown"}

    # Case ID
    case_id = manifest.get("case_id", "")
    checks["case_id"] = {"value": case_id, "pass": bool(case_id) and case_id != "unknown"}

    # Task SHA256
    task_sha = manifest.get("task_sha256", "")
    checks["task_sha256"] = {"value": task_sha[:16] + "..." if task_sha else "missing", "pass": bool(task_sha)}

    # Input SHA256
    input_sha = manifest.get("input_sha256", {})
    checks["input_sha256"] = {
        "value": f"{len(input_sha)} files" if input_sha else "0 files",
        "pass": True,  # Empty is OK for EDIT if no references
    }

    # Skills SHA256
    skills_sha = manifest.get("skills_sha256", {})
    checks["skills_sha256"] = {
        "value": f"{len(skills_sha)} files" if skills_sha else "0 files",
        "pass": True,
    }

    # Docker image
    docker_image = manifest.get("docker_image", "")
    docker_image_id = manifest.get("docker_image_id", "")
    checks["docker_image"] = {
        "value": docker_image,
        "pass": bool(docker_image),
    }
    checks["docker_image_id"] = {
        "value": docker_image_id[:24] + "..." if docker_image_id else "unknown",
        "pass": bool(docker_image_id) and docker_image_id != "unknown",
    }

    # Agent
    agent = manifest.get("agent", "")
    checks["agent"] = {"value": agent, "pass": bool(agent) and agent == "OpenClaw"}

    # Agent version
    agent_version = manifest.get("agent_version", "")
    checks["agent_version"] = {
        "value": agent_version,
        "pass": bool(agent_version) and agent_version != "unknown",
    }

    # Agent model
    agent_model = manifest.get("agent_model", "")
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
        print(f"  {status}: {name} = {check['value']}")

    print(f"\nOverall: {'PASS' if result['pass'] else 'FAIL'}")
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
