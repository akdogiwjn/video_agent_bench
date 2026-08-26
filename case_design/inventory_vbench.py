#!/usr/bin/env python3
"""Inventory VBench public prompt suite for GEN case candidates.

Scans the frozen VBench prompt files and produces a candidate list
with SHA256 hashes, categories, and source file paths.

VBench provides two prompt sets:
1. prompts_per_category/<category>.txt — 99 short prompts per category
2. augmented_prompts/gpt_enhanced_prompts/prompts_per_category_longer/<category>_longer.txt
   — 99 GPT-enhanced longer prompts per category

Both sets are scanned. Each prompt is recorded with its source file,
line number, and SHA256 hash.

Usage:
    python3 case_design/inventory_vbench.py --prompts-root upstream/vbench/prompts [--output <path>]

Output: evidence/case_selection/vbench_candidates.json
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


CATEGORIES = [
    "animal", "architecture", "food", "human",
    "lifestyle", "plant", "scenery", "vehicles",
]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scan_prompt_file(filepath: Path, category: str, prompt_type: str, source_commit: str, project_root: Path | None = None) -> list[dict]:
    """Scan a single prompt file and return one candidate per prompt line."""
    if not filepath.is_file():
        return []

    # Use relative path from project root if available
    if project_root is not None:
        try:
            source_file = str(filepath.relative_to(project_root))
        except ValueError:
            source_file = str(filepath)
    else:
        source_file = str(filepath)

    candidates = []
    lines = filepath.read_text(encoding="utf-8").strip().split("\n")
    for i, line in enumerate(lines):
        prompt = line.strip()
        if not prompt:
            continue

        prompt_id = f"{prompt_type}_{category}_{i+1:03d}"
        candidates.append({
            "prompt_id": prompt_id,
            "prompt": prompt,
            "source_file": source_file,
            "source_commit": source_commit,
            "sha256": sha256_text(prompt),
            "category": category,
            "prompt_type": prompt_type,
            "line_number": i + 1,
            "selected": False,
            "selection_reason": "",
        })
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Inventory VBench prompt suite")
    parser.add_argument(
        "--prompts-root",
        default="upstream/vbench/prompts",
        help="Path to the frozen VBench prompts/ directory",
    )
    parser.add_argument(
        "--commit",
        default=None,
        help="VBench commit SHA (read from upstream/vbench/COMMIT if not specified)",
    )
    parser.add_argument(
        "--output",
        default="evidence/case_selection/vbench_candidates.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    prompts_root = Path(args.prompts_root).resolve()
    output = Path(args.output)

    commit = args.commit
    if not commit:
        commit_file = Path("upstream/vbench/COMMIT")
        if commit_file.is_file():
            commit = commit_file.read_text().strip()
        else:
            commit = "unknown"

    # Use relative path from project root
    project_root = Path(__file__).resolve().parent.parent
    try:
        prompts_root_rel = str(prompts_root.relative_to(project_root))
    except ValueError:
        prompts_root_rel = str(prompts_root)

    result = {
        "benchmark": "VBench",
        "repository": "Vchitect/VBench",
        "commit": commit,
        "prompts_root": prompts_root_rel,
        "prompt_sets": ["original", "gpt_enhanced_longer"],
        "total_prompts": 0,
        "prompts": [],
        "notes": [],
    }

    if not prompts_root.is_dir():
        result["notes"].append(f"Prompts root not found: {prompts_root}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Prompts root not found: {prompts_root}")
        sys.exit(1)

    # Determine project root for relative paths
    project_root = Path(__file__).resolve().parent.parent

    # Scan original prompts
    orig_dir = prompts_root / "prompts_per_category"
    for category in CATEGORIES:
        f = orig_dir / f"{category}.txt"
        prompts = scan_prompt_file(f, category, "original", commit, project_root)
        result["prompts"].extend(prompts)

    # Scan GPT-enhanced longer prompts
    longer_dir = prompts_root / "augmented_prompts" / "gpt_enhanced_prompts" / "prompts_per_category_longer"
    for category in CATEGORIES:
        f = longer_dir / f"{category}_longer.txt"
        prompts = scan_prompt_file(f, category, "gpt_enhanced_longer", commit, project_root)
        result["prompts"].extend(prompts)

    result["total_prompts"] = len(result["prompts"])

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    orig_count = sum(1 for p in result["prompts"] if p["prompt_type"] == "original")
    longer_count = sum(1 for p in result["prompts"] if p["prompt_type"] == "gpt_enhanced_longer")

    print(f"Scanned {prompts_root}")
    print(f"  commit: {commit}")
    print(f"  original prompts: {orig_count}")
    print(f"  gpt-enhanced longer prompts: {longer_count}")
    print(f"  total prompts: {result['total_prompts']}")
    print(f"  output: {output}")


if __name__ == "__main__":
    main()
