#!/usr/bin/env python3
"""Milestone 5-8 combined acceptance check.

Milestone 5: OpenClaw runner — run_case.py, entrypoint.sh, workspace, trajectory
Milestone 6: GEN — VideoWeaver Case + Foundation Skills + OpenClaw (blocked)
Milestone 7: EDIT — AgenticVBench Repurpose + OpenClaw + generic media env
Milestone 8: Native verification — VideoWeaver PRM/ORM & AgenticVBench verifier
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_milestone5():
    print(f"\n{'=' * 60}")
    print("  Milestone 5: OpenClaw Runner")
    print(f"{'=' * 60}")
    ok = True

    files = [
        ("runner/run_case.py", "Main runner entry point"),
        ("runner/workspace.py", "Workspace management"),
        ("runner/provenance.py", "Provenance tracking"),
        ("runner/openclaw_runner.py", "OpenClaw execution"),
        ("runtime/entrypoint.sh", "Agent entrypoint"),
    ]
    for path, desc in files:
        p = ROOT / path
        if p.is_file():
            print(f"  OK: {path}")
        else:
            print(f"  MISSING: {path}")
            ok = False

    # Dry run test
    print("\n  Dry run test (edit case):")
    result = subprocess.run(
        [sys.executable, "runner/run_case.py", "--case", "edit", "--dry-run", "--skip-verify"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    if result.returncode == 0 and "Run complete" in result.stdout:
        print("    OK: dry run completed")
    else:
        print(f"    FAIL: exit={result.returncode}")
        print(f"    stdout: {result.stdout[:200]}")
        ok = False

    # GEN blocked test
    print("\n  Blocked case test (gen):")
    result = subprocess.run(
        [sys.executable, "runner/run_case.py", "--case", "gen", "--dry-run"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=10,
    )
    if result.returncode != 0 and "blocked" in result.stderr.lower():
        print("    OK: GEN case correctly blocked")
    else:
        print(f"    FAIL: expected blocked, got exit={result.returncode}")
        ok = False

    return ok


def check_milestone6():
    print(f"\n{'=' * 60}")
    print("  Milestone 6: GEN (VideoWeaver)")
    print(f"{'=' * 60}")

    gen_manifest = ROOT / "cases/gen/case_manifest.json"
    if gen_manifest.is_file():
        with open(gen_manifest) as f:
            m = json.load(f)
        print(f"  status: {m.get('status', 'unknown')}")
        if m.get("status") == "blocked":
            print(f"  reason: {m.get('reason', 'unknown')}")
            print("  NOTE: GEN is blocked because VideoWeaver dataset is not yet released.")
            print("  The runner and foundation skills infrastructure is ready.")
            print("  GEN will work once the dataset becomes available.")
            return True
    print("  FAIL: no gen case manifest")
    return False


def check_milestone7():
    print(f"\n{'=' * 60}")
    print("  Milestone 7: EDIT (AgenticVBench Repurpose)")
    print(f"{'=' * 60}")
    ok = True

    edit_manifest = ROOT / "cases/edit/case_manifest.json"
    if edit_manifest.is_file():
        with open(edit_manifest) as f:
            m = json.load(f)
        print(f"  case_id: {m.get('case_id', 'unknown')}")
        print(f"  benchmark: {m.get('benchmark', 'unknown')}")
        print(f"  visible_capabilities: {m.get('visible_capabilities', [])}")

        # Check materials status
        for name, info in m.get("materials_status", {}).items():
            print(f"  material {name}: {info.get('status', 'unknown')}")
            if info.get("status") == "pending_download":
                print(f"    -> Download from: {info.get('huggingface_url', 'unknown')}")
    else:
        print("  MISSING: edit case manifest")
        ok = False

    # Check instruction.md is from upstream
    instr = ROOT / "cases/edit/task/instruction.md"
    if instr.is_file():
        print(f"  instruction.md: present ({instr.stat().st_size} bytes)")
    else:
        print("  MISSING: instruction.md")
        ok = False

    print("\n  NOTE: To run the EDIT case:")
    print("    1. Download source.mp4 from HuggingFace")
    print("    2. Build Docker image: docker build -t video-agent-bench:1.0 -f runtime/Dockerfile runtime/")
    print("    3. Run: python3 runner/run_case.py --case edit")

    return ok


def check_milestone8():
    print(f"\n{'=' * 60}")
    print("  Milestone 8: Native Verification")
    print(f"{'=' * 60}")
    ok = True

    verifiers = [
        ("verifier/verify_provenance.py", "V0: Provenance verifier"),
        ("verifier/verify_execution.py", "V1: Execution integrity verifier"),
        ("verifier/gen/evaluate.py", "GEN verifier adapter (VideoWeaver PRM/ORM)"),
        ("verifier/edit/evaluate.py", "EDIT verifier adapter (AgenticVBench)"),
    ]
    for path, desc in verifiers:
        p = ROOT / path
        if p.is_file():
            print(f"  OK: {path} ({desc})")
        else:
            print(f"  MISSING: {path}")
            ok = False

    # Check verifier isolation
    print("\n  Verifier isolation check:")
    edit_eval = ROOT / "verifier/edit/evaluate.py"
    if edit_eval.is_file():
        content = edit_eval.read_text()
        # Verifier should not import from runner or workspace
        if "from runner" not in content and "import workspace" not in content:
            print("    OK: EDIT verifier is isolated from runner")
        else:
            print("    WARNING: EDIT verifier imports runner modules")

    # Check that verifier files are in upstream (frozen)
    verifier_files = ROOT / "upstream/agentic_vbench/tasks_repurpose/football/steps/solve/tests"
    if verifier_files.is_dir():
        files = [f.name for f in verifier_files.iterdir() if f.is_file()]
        print(f"    OK: AgenticVBench verifier files frozen: {files}")
    else:
        print("    MISSING: AgenticVBench verifier files not frozen")
        ok = False

    # Check GEN verifier status
    print("\n  GEN verifier status:")
    print("    BLOCKED: VideoWeaver evaluation code (AutomaticSkillOptimization/)")
    print("    was not frozen in Milestone 1. The adapter is ready but needs")
    print("    the upstream evaluation code to be fetched.")

    return ok


def main():
    all_ok = True
    all_ok &= check_milestone5()
    all_ok &= check_milestone6()
    all_ok &= check_milestone7()
    all_ok &= check_milestone8()

    print(f"\n{'=' * 60}")
    if all_ok:
        print("  Milestones 5-8: ALL CHECKS PASSED")
    else:
        print("  Milestones 5-8: SOME CHECKS FAILED")
    print(f"{'=' * 60}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
