#!/usr/bin/env python3
"""Milestone 1 acceptance check: print commits, scan VBench prompts, scan Repurpose tasks.

NOTE: This is a STATIC SPEC CHECK, not an E2E test.
"""
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

    print_section("1. Benchmark Commits")
    for name, path in [
        ("VBench", "upstream/vbench/COMMIT"),
        ("VideoWeaver", "upstream/videoweaver/COMMIT"),
        ("AgenticVBench", "upstream/agentic_vbench/COMMIT"),
    ]:
        f = ROOT / path
        if f.is_file():
            commit = f.read_text().strip()
            print(f"  {name}: {commit}")
        else:
            print(f"  {name}: MISSING")
            all_ok = False

    print_section("2. VBench Prompts (GEN task content source)")
    vb_candidates = ROOT / "evidence/case_selection/vbench_candidates.json"
    if vb_candidates.is_file():
        with open(vb_candidates) as f:
            data = json.load(f)
        print(f"  total prompts: {data['total_prompts']}")
        orig = sum(1 for p in data["prompts"] if p["prompt_type"] == "original")
        longer = sum(1 for p in data["prompts"] if p["prompt_type"] == "gpt_enhanced_longer")
        print(f"  original: {orig}")
        print(f"  gpt-enhanced longer: {longer}")
    else:
        print("  candidates file not found")
        all_ok = False

    print_section("2b. VideoWeaver Dataset (RESERVED)")
    vw_candidates = ROOT / "evidence/case_selection/videoweaver_candidates.json"
    if vw_candidates.is_file():
        with open(vw_candidates) as f:
            data = json.load(f)
        print(f"  status: {data.get('status', 'unknown')}")
    else:
        print("  candidates file not found")

    print_section("3. AgenticVBench Repurpose Tasks")
    avb_candidates = ROOT / "evidence/case_selection/agentic_vbench_repurpose_candidates.json"
    if avb_candidates.is_file():
        with open(avb_candidates) as f:
            data = json.load(f)
        print(f"  total tasks: {data['total_tasks']}")
        with_verifier = sum(1 for t in data["tasks"] if t["verifier_available"])
        print(f"  with verifier: {with_verifier}")
    else:
        print("  candidates file not found")
        all_ok = False

    print_section("4. Source Manifests")
    for name, path in [
        ("VBench", "upstream/vbench/prompts/source_manifest.json"),
        ("VideoWeaver", "upstream/videoweaver/skills/source_manifest.json"),
        ("AgenticVBench", "upstream/agentic_vbench/source_manifest.json"),
    ]:
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
        print("Milestone 1: STATIC CHECKS PASSED")
    else:
        print("Milestone 1: SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
