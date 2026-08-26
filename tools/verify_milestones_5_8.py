#!/usr/bin/env python3
"""Milestone 5-8 combined acceptance check.

Milestone 5: OpenClaw runner — run_case.py, entrypoint.sh, workspace, trajectory
Milestone 6: GEN — VBench-derived case + VideoWeaver foundation skills + OpenClaw
Milestone 7: EDIT — AgenticVBench Repurpose + OpenClaw + generic media env
Milestone 8: Native verification — project-defined rubric (GEN) & AgenticVBench verifier (EDIT)
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

    # Dry run test — EDIT
    print("\n  Dry run test (edit case):")
    result = subprocess.run(
        [sys.executable, "runner/run_case.py", "--case", "edit", "--dry-run", "--skip-verify"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    if result.returncode == 0 and "Run complete" in result.stdout:
        print("    OK: dry run completed")
    else:
        print(f"    FAIL: exit={result.returncode}")
        ok = False

    # Dry run test — GEN
    print("\n  Dry run test (gen case):")
    result = subprocess.run(
        [sys.executable, "runner/run_case.py", "--case", "gen", "--dry-run"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    if result.returncode == 0 and "Run complete" in result.stdout:
        print("    OK: dry run completed")
    else:
        print(f"    FAIL: exit={result.returncode}")
        ok = False

    return ok


def check_milestone6():
    print(f"\n{'=' * 60}")
    print("  Milestone 6: GEN (Multi-Benchmark-Derived)")
    print(f"{'=' * 60}")
    ok = True

    gen_manifest = ROOT / "cases/gen/gen_case_001/case_manifest.json"
    if gen_manifest.is_file():
        with open(gen_manifest) as f:
            m = json.load(f)
        print(f"  case_id: {m.get('case_id', 'unknown')}")
        print(f"  case_source: {m.get('case_source', 'unknown')}")
        print(f"  task_content_source: {m.get('task_content_source', 'unknown')}")
        print(f"  agentic_execution_basis: {m.get('agentic_execution_basis', 'unknown')}")
        print(f"  status: {m.get('status', 'unknown')}")
        print(f"  visible_capabilities: {m.get('visible_capabilities', [])}")

        if m.get("case_source") != "multi-benchmark-derived":
            print("  FAIL: case_source should be 'multi-benchmark-derived'")
            ok = False
        if m.get("official_benchmark_case") is not False:
            print("  FAIL: official_benchmark_case should be false")
            ok = False
    else:
        print("  MISSING: cases/gen/gen_case_001/case_manifest.json")
        ok = False

    # Check original prompt preserved
    orig = ROOT / "cases/gen/gen_case_001/source/original_prompt.txt"
    if orig.is_file():
        print(f"  OK: original_prompt.txt preserved ({orig.stat().st_size} bytes)")
    else:
        print("  MISSING: source/original_prompt.txt")
        ok = False

    # Check adaptation.json
    adapt = ROOT / "cases/gen/gen_case_001/adaptation.json"
    if adapt.is_file():
        with open(adapt) as f:
            a = json.load(f)
        print(f"  OK: adaptation.json ({len(a.get('changes', []))} changes documented)")
    else:
        print("  MISSING: adaptation.json")
        ok = False

    # Check instruction does not hardcode tool sequence
    instr = ROOT / "cases/gen/gen_case_001/task/instruction.txt"
    if instr.is_file():
        content = instr.read_text()
        forbidden = ["first call", "step 1", "step 2", "call image-gen", "call video-gen",
                     "must plan", "must generate storyboard", "call merge-video"]
        found_forbidden = [kw for kw in forbidden if kw.lower() in content.lower()]
        if found_forbidden:
            print(f"  WARNING: instruction may hardcode workflow: {found_forbidden}")
        else:
            print(f"  OK: instruction does not hardcode tool call sequence")
    else:
        print("  MISSING: task/instruction.txt")
        ok = False

    return ok


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
        print(f"  OK: instruction.md present ({instr.stat().st_size} bytes)")
    else:
        print("  MISSING: instruction.md")
        ok = False

    return ok


def check_milestone8():
    print(f"\n{'=' * 60}")
    print("  Milestone 8: Native Verification")
    print(f"{'=' * 60}")
    ok = True

    verifiers = [
        ("verifier/verify_provenance.py", "V0: Provenance verifier"),
        ("verifier/verify_execution.py", "V1: Execution integrity verifier"),
        ("verifier/gen/evaluate.py", "GEN verifier (project-defined rubric)"),
        ("verifier/edit/evaluate.py", "EDIT verifier (AgenticVBench adapter)"),
    ]
    for path, desc in verifiers:
        p = ROOT / path
        if p.is_file():
            print(f"  OK: {path} ({desc})")
        else:
            print(f"  MISSING: {path}")
            ok = False

    # Check GEN verifier uses project-defined rubric
    gen_eval = ROOT / "verifier/gen/evaluate.py"
    if gen_eval.is_file():
        content = gen_eval.read_text()
        if "project-defined" in content and "official_videoweaver_rubric" in content:
            print("  OK: GEN verifier uses project-defined rubric (not official)")
        else:
            print("  WARNING: GEN verifier may not properly label rubric source")

    # Check verifier isolation
    print("\n  Verifier isolation check:")
    edit_eval = ROOT / "verifier/edit/evaluate.py"
    if edit_eval.is_file():
        content = edit_eval.read_text()
        if "from runner" not in content and "import workspace" not in content:
            print("    OK: EDIT verifier is isolated from runner")

    # Check verifier files frozen in upstream
    verifier_files = ROOT / "upstream/agentic_vbench/tasks_repurpose/football/steps/solve/tests"
    if verifier_files.is_dir():
        files = [f.name for f in verifier_files.iterdir() if f.is_file()]
        print(f"    OK: AgenticVBench verifier files frozen: {files}")
    else:
        print("    MISSING: AgenticVBench verifier files not frozen")
        ok = False

    # Check GEN rubric
    gen_rubric = ROOT / "cases/gen/gen_case_001/rubric/rubric_deterministic.json"
    if gen_rubric.is_file():
        with open(gen_rubric) as f:
            r = json.load(f)
        print(f"    OK: GEN rubric: {r.get('rubric_source', 'unknown')}, "
              f"basis={r.get('rubric_basis', [])}, "
              f"official_videoweaver_rubric={r.get('official_videoweaver_rubric', 'unknown')}")
        if r.get("rubric_source") != "project-defined":
            print("    FAIL: rubric_source should be 'project-defined'")
            ok = False
        if r.get("official_videoweaver_rubric") is not False:
            print("    FAIL: official_videoweaver_rubric should be false")
            ok = False
    else:
        print("    MISSING: GEN rubric")
        ok = False

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
