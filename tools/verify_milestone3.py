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

    # --- EDIT case ---
    print("=== EDIT case (football) ===")
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

    # --- GEN case ---
    print("\n=== GEN case ===")
    gen_manifest = ROOT / "cases/gen/case_manifest.json"
    if gen_manifest.is_file():
        with open(gen_manifest) as f:
            gmanifest = json.load(f)
        print(f"  status: {gmanifest.get('status', 'unknown')}")
        if gmanifest.get("status") == "blocked":
            print(f"  reason: {gmanifest.get('reason', 'unknown')}")
    else:
        print("  FAIL: cases/gen/case_manifest.json not found")
        all_ok = False

    print()
    if all_ok:
        print("Milestone 3: ALL CHECKS PASSED")
    else:
        print("Milestone 3: SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
