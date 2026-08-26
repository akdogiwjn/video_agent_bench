#!/usr/bin/env python3
"""Milestone 1 acceptance check: print commits, scan VideoWeaver cases, scan Repurpose tasks."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def print_section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main():
    all_ok = True

    # --- 1. Print both benchmark commits ---
    print_section("1. Benchmark Commits")
    for name, path in [("VideoWeaver", "upstream/videoweaver/COMMIT"), ("AgenticVBench", "upstream/agentic_vbench/COMMIT")]:
        f = ROOT / path
        if f.is_file():
            commit = f.read_text().strip()
            print(f"  {name}: {commit}")
        else:
            print(f"  {name}: MISSING")
            all_ok = False

    # --- 2. VideoWeaver cases ---
    print_section("2. VideoWeaver Cases")
    vw_candidates = ROOT / "evidence/case_selection/videoweaver_candidates.json"
    if vw_candidates.is_file():
        with open(vw_candidates) as f:
            data = json.load(f)
        print(f"  total cases: {data['total_cases']}")
        print(f"  categories: {data['categories']}")
        if data["total_cases"] == 0:
            for note in data.get("notes", []):
                print(f"  note: {note}")
    else:
        print("  candidates file not found — run inventory script first")
        all_ok = False

    # --- 3. AgenticVBench Repurpose tasks ---
    print_section("3. AgenticVBench Repurpose Tasks")
    avb_candidates = ROOT / "evidence/case_selection/agentic_vbench_repurpose_candidates.json"
    if avb_candidates.is_file():
        with open(avb_candidates) as f:
            data = json.load(f)
        print(f"  total tasks: {data['total_tasks']}")
        with_verifier = sum(1 for t in data["tasks"] if t["verifier_available"])
        print(f"  with verifier: {with_verifier}")
    else:
        print("  candidates file not found — run inventory script first")
        all_ok = False

    # --- 4. Source manifests ---
    print_section("4. Source Manifests")
    for name, path in [("VideoWeaver", "upstream/videoweaver/source_manifest.json"), ("AgenticVBench", "upstream/agentic_vbench/source_manifest.json")]:
        f = ROOT / path
        if f.is_file():
            with open(f) as fh:
                m = json.load(fh)
            print(f"  {name}: {m['file_count']} files, commit={m['commit'][:12]}...")
        else:
            print(f"  {name}: MISSING")
            all_ok = False

    print()
    if all_ok:
        print("Milestone 1: ALL CHECKS PASSED")
    else:
        print("Milestone 1: SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
