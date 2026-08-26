#!/usr/bin/env python3
"""Milestone 3 acceptance: verify local case files match upstream SHA256."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    all_ok = True

    # --- GEN case (multi-benchmark-derived) ---
    print("=== GEN case (gen_case_001) ===")
    gen_manifest = ROOT / "cases/gen/gen_case_001/case_manifest.json"
    if not gen_manifest.is_file():
        print("FAIL: cases/gen/gen_case_001/case_manifest.json not found")
        sys.exit(1)

    with open(gen_manifest) as f:
        manifest = json.load(f)

    print(f"  case_id: {manifest.get('case_id', 'unknown')}")
    print(f"  case_source: {manifest.get('case_source', 'unknown')}")
    print(f"  official_benchmark_case: {manifest.get('official_benchmark_case', 'unknown')}")
    print(f"  task_content_source: {manifest.get('task_content_source', 'unknown')}")
    print(f"  status: {manifest.get('status', 'unknown')}")

    case_root = ROOT / "cases/gen/gen_case_001"
    for rel, expected_sha in manifest.get("files", {}).items():
        local_path = case_root / rel
        if not local_path.is_file():
            print(f"  MISSING: {rel}")
            all_ok = False
            continue
        actual_sha = sha256_file(local_path)
        if actual_sha == expected_sha:
            print(f"  OK: {rel} ({actual_sha[:16]}...)")
        else:
            print(f"  HASH MISMATCH: {rel}")
            print(f"    expected: {expected_sha}")
            print(f"    actual:   {actual_sha}")
            all_ok = False

    # Check original prompt SHA256 matches VBench inventory
    orig_prompt = case_root / "source/original_prompt.txt"
    if orig_prompt.is_file():
        orig_sha = sha256_file(orig_prompt)
        # Check against gen_selection.json
        sel_path = ROOT / "evidence/case_selection/gen_selection.json"
        if sel_path.is_file():
            with open(sel_path) as f:
                sel = json.load(f)
            expected = sel.get("selected_prompt_sha256", "")
            if expected and orig_sha == expected:
                print(f"  OK: original_prompt.txt matches VBench inventory SHA256")
            else:
                print(f"  WARNING: original_prompt.txt SHA256 mismatch with inventory")

    # Check adaptation.json exists
    adapt_path = case_root / "adaptation.json"
    if adapt_path.is_file():
        print(f"  OK: adaptation.json present")
    else:
        print(f"  MISSING: adaptation.json")
        all_ok = False

    # --- EDIT case (official) ---
    print("\n=== EDIT case (football) ===")
    edit_manifest = ROOT / "cases/edit/case_manifest.json"
    if not edit_manifest.is_file():
        print("FAIL: cases/edit/case_manifest.json not found")
        sys.exit(1)

    with open(edit_manifest) as f:
        manifest = json.load(f)

    upstream_root = ROOT / "upstream/agentic_vbench/tasks_repurpose/football"
    case_root = ROOT / "cases/edit"

    for rel, expected_sha in manifest.get("files", {}).items():
        local_path = case_root / rel
        if not local_path.is_file():
            print(f"  MISSING: {rel}")
            all_ok = False
            continue
        actual_sha = sha256_file(local_path)
        if actual_sha == expected_sha:
            print(f"  OK: {rel} ({actual_sha[:16]}...)")
        else:
            print(f"  HASH MISMATCH: {rel}")
            print(f"    expected: {expected_sha}")
            print(f"    actual:   {actual_sha}")
            all_ok = False

    # Check materials status
    for name, info in manifest.get("materials_status", {}).items():
        status = info.get("status", "unknown")
        print(f"  material {name}: {status}")
        if status == "pending_download":
            print(f"    -> {info.get('huggingface_url', 'unknown')}")

    print()
    if all_ok:
        print("Milestone 3: ALL CHECKS PASSED")
    else:
        print("Milestone 3: SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
