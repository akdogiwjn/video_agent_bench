#!/usr/bin/env python3
"""Milestone 5-8 combined acceptance check.

NOTE: These are STATIC SPEC CHECKS, not E2E acceptance tests.
They verify that files exist and basic dry-runs succeed, but do NOT
verify that:
- OpenClaw actually ran and produced real video output
- Real trajectory data was collected
- Verifiers actually passed on real agent output
- A black video would be rejected

For E2E verification, run:
    python3 runner/run_case.py --case gen --model <model>
    python3 runner/run_case.py --case edit --model <model>
Then inspect results/<run-id>/ for real trajectory and verification_result.json.

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
        ("runner/workspace.py", "Workspace management + skill dependency resolver"),
        ("runner/provenance.py", "Provenance tracking"),
        ("runner/openclaw_runner.py", "OpenClaw execution + raw trajectory persistence"),
        ("runtime/entrypoint.sh", "Agent entrypoint (with openclaw.json config)"),
    ]
    for path, desc in files:
        p = ROOT / path
        if p.is_file():
            print(f"  OK: {path}")
        else:
            print(f"  MISSING: {path}")
            ok = False

    # Check entrypoint has openclaw.json config
    entrypoint = ROOT / "runtime/entrypoint.sh"
    if entrypoint.is_file():
        content = entrypoint.read_text()
        if "openclaw.json" in content and "extraDirs" in content and "exec-approvals" in content:
            print("  OK: entrypoint.sh configures OpenClaw skills + approvals")
        else:
            print("  FAIL: entrypoint.sh missing OpenClaw configuration")
            ok = False

    # Check openclaw_runner mounts /root/.openclaw
    runner = ROOT / "runner/openclaw_runner.py"
    if runner.is_file():
        content = runner.read_text()
        if "/root/.openclaw" in content and "openclaw_state_dir" in content:
            print("  OK: runner persists raw OpenClaw state")
        else:
            print("  FAIL: runner does not persist OpenClaw state")
            ok = False

    # Check run_case.py calls verifier
    run_case = ROOT / "runner/run_case.py"
    if run_case.is_file():
        content = run_case.read_text()
        if "run_verifier" in content and "deferred" not in content:
            print("  OK: runner calls verifier (not deferred)")
        else:
            print("  FAIL: runner does not call verifier")
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

    orig = ROOT / "cases/gen/gen_case_001/source/original_prompt.txt"
    if orig.is_file():
        print(f"  OK: original_prompt.txt preserved ({orig.stat().st_size} bytes)")
    else:
        print("  MISSING: source/original_prompt.txt")
        ok = False

    adapt = ROOT / "cases/gen/gen_case_001/adaptation.json"
    if adapt.is_file():
        with open(adapt) as f:
            a = json.load(f)
        print(f"  OK: adaptation.json ({len(a.get('changes', []))} changes documented)")
    else:
        print("  MISSING: adaptation.json")
        ok = False

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

    # Check skill dependency closure includes get-output-dir
    ws = ROOT / "runner/workspace.py"
    if ws.is_file():
        content = ws.read_text()
        if "SKILL_DEPENDENCIES" in content and "resolve_skill_dependencies" in content:
            print("  OK: skill dependency resolver present")
        else:
            print("  FAIL: skill dependency resolver missing")
            ok = False

    print("\n  E2E STATUS: NOT VERIFIED (requires real Docker + OpenClaw run)")
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
        print(f"  case_source: {m.get('case_source', 'unknown')}")
        print(f"  official_benchmark_case: {m.get('official_benchmark_case', 'unknown')}")
        print(f"  visible_capabilities: {m.get('visible_capabilities', [])}")

        if m.get("case_source") != "official":
            print("  FAIL: case_source should be 'official'")
            ok = False
        if m.get("official_benchmark_case") is not True:
            print("  FAIL: official_benchmark_case should be true")
            ok = False

        # Check source.mp4
        materials = m.get("materials", {})
        if "source.mp4" in materials:
            mat = materials["source.mp4"]
            print(f"  source.mp4: {mat.get('status', 'unknown')} ({mat.get('size_bytes', 0):,} bytes)")
            if mat.get("status") == "frozen":
                print(f"    SHA256: {mat.get('sha256', 'unknown')[:16]}...")
                print(f"    duration: {mat.get('duration_seconds', '?')}s")
            else:
                print(f"  WARNING: source.mp4 not frozen")
        else:
            # Check old materials_status format
            ms = m.get("materials_status", {})
            if "source.mp4" in ms:
                print(f"  source.mp4: {ms['source.mp4'].get('status', 'unknown')}")
            else:
                print("  MISSING: source.mp4 info")
                ok = False
    else:
        print("  MISSING: edit case manifest")
        ok = False

    instr = ROOT / "cases/edit/task/instruction.md"
    if instr.is_file():
        print(f"  OK: instruction.md present ({instr.stat().st_size} bytes)")
    else:
        print("  MISSING: instruction.md")
        ok = False

    # Check verifier uses Docker container
    edit_eval = ROOT / "verifier/edit/evaluate.py"
    if edit_eval.is_file():
        content = edit_eval.read_text()
        if "run_verifier_in_docker" in content and "/tests" in content and "/baked" in content:
            print("  OK: EDIT verifier uses Docker container with correct path mapping")
        else:
            print("  FAIL: EDIT verifier path mapping incorrect")
            ok = False

    print("\n  E2E STATUS: NOT VERIFIED (requires real Docker + OpenClaw run)")
    return ok


def check_milestone8():
    print(f"\n{'=' * 60}")
    print("  Milestone 8: Native Verification")
    print(f"{'=' * 60}")
    ok = True

    verifiers = [
        ("verifier/verify_provenance.py", "V0: Provenance verifier"),
        ("verifier/verify_execution.py", "V1: Execution integrity verifier"),
        ("verifier/gen/evaluate.py", "GEN verifier (project-defined rubric + hard gates)"),
        ("verifier/edit/evaluate.py", "EDIT verifier (AgenticVBench Docker adapter)"),
    ]
    for path, desc in verifiers:
        p = ROOT / path
        if p.is_file():
            print(f"  OK: {path} ({desc})")
        else:
            print(f"  MISSING: {path}")
            ok = False

    # Check GEN verifier has hard gates
    gen_eval = ROOT / "verifier/gen/evaluate.py"
    if gen_eval.is_file():
        content = gen_eval.read_text()
        if "hard_gates" in content and "is_black_or_solid" in content and "format_pass and content_pass and process_pass" in content:
            print("  OK: GEN verifier has hard gates (black video must FAIL)")
        else:
            print("  FAIL: GEN verifier missing hard gates")
            ok = False

    # Check verifier isolation
    print("\n  Verifier isolation check:")
    edit_eval = ROOT / "verifier/edit/evaluate.py"
    if edit_eval.is_file():
        content = edit_eval.read_text()
        if "from runner" not in content and "import workspace" not in content:
            print("    OK: EDIT verifier is isolated from runner")

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
    else:
        print("    MISSING: GEN rubric")
        ok = False

    # Check VLM/ASR adapters exist
    vlm_adapter = ROOT / "tools/media/vlm_understand.py"
    asr_adapter = ROOT / "tools/media/asr_transcribe.py"
    if vlm_adapter.is_file() and asr_adapter.is_file():
        print("    OK: VLM and ASR capability adapters present")
    else:
        print("    MISSING: VLM/ASR capability adapters")

    # Check verify_execution has hard checks
    exec_verifier = ROOT / "verifier/verify_execution.py"
    if exec_verifier.is_file():
        content = exec_verifier.read_text()
        if "exit_code == 0" in content and "tool_call_count > 0" in content and "mtime" in content:
            print("    OK: verify_execution.py has strict checks (exit_code==0, tool_calls>0, mtime)")
        else:
            print("    WARNING: verify_execution.py checks may be too weak")

    print("\n  E2E STATUS: NOT VERIFIED (requires real verifier run on real agent output)")
    return ok


def main():
    all_ok = True
    all_ok &= check_milestone5()
    all_ok &= check_milestone6()
    all_ok &= check_milestone7()
    all_ok &= check_milestone8()

    print(f"\n{'=' * 60}")
    if all_ok:
        print("  STATIC CHECKS PASSED — E2E NOT VERIFIED")
        print("  Run real Docker + OpenClaw to verify E2E.")
    else:
        print("  SOME CHECKS FAILED")
    print(f"{'=' * 60}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
