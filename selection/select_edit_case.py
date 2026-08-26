#!/usr/bin/env python3
"""Select a representative EDIT case from AgenticVBench Repurpose inventory.

Selection rules (from project plan):
1. family == repurpose
2. Longer source video (observable: can't measure without download — pass all, note limitation)
3. Creative brief clear (observable: instruction_length > threshold)
4. Not simple fixed-time trimming (observable: instruction contains re-cut/repurpose keywords)
5. Needs content selection (observable: instruction contains selection keywords)
6. Needs reorganization (observable: instruction contains reorganization keywords)
7. Verifier available (observable: verifier_available == True)
8. Materials obtainable (observable: source_materials not empty)

Then select a medium-above complexity task from the filtered set.

Usage:
    python3 selection/select_edit_case.py [--candidates <path>] [--output <path>]

Output: evidence/case_selection/edit_selection.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Keyword sets for observable text-based filtering.
# These are NOT semantic interpretations — they are explicit string patterns
# found in the official instruction text.
RE_CUT_KEYWORDS = [
    "repurpose", "re-cut", "recut", "re-edit", "distill",
    "reshape", "remix", "rework", "transform", "short",
]
SELECTION_KEYWORDS = [
    "select", "choose", "pick", "find", "identify", "isolate",
    "highlight", "moment", "best", "key",
]
REORG_KEYWORDS = [
    "reorder", "rearrange", "sequence", "structure", "narrative",
    "arc", "build", "mount", "progress", "flow", "timeline",
    "open on", "close on", "start with", "end with",
]


def has_any_keyword(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def count_keyword_matches(text: str, keywords: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def filter_edit_cases(tasks: list[dict], instructions: dict[str, str]) -> list[dict]:
    """Apply EDIT selection rules to candidate tasks."""
    filtered = []
    for task in tasks:
        rules_passed = []

        # Rule 1: family == repurpose
        if task["family"] != "repurpose":
            continue
        rules_passed.append("family_repurpose")

        # Rule 2: Longer source — can't measure without download
        rules_passed.append("longer_source_unknown")

        # Rule 3: Creative brief clear — instruction length threshold
        instr_len = task.get("instruction_length_chars", 0)
        if instr_len >= 1500:
            rules_passed.append("brief_clear")
        else:
            continue

        # Rule 4: Not simple fixed-time trimming
        instr_text = instructions.get(task["task_id"], "")
        if not has_any_keyword(instr_text, RE_CUT_KEYWORDS):
            continue
        rules_passed.append("not_simple_trim")

        # Rule 5: Needs content selection
        if not has_any_keyword(instr_text, SELECTION_KEYWORDS):
            continue
        rules_passed.append("needs_content_selection")

        # Rule 6: Needs reorganization
        if not has_any_keyword(instr_text, REORG_KEYWORDS):
            continue
        rules_passed.append("needs_reorganization")

        # Rule 7: Verifier available
        if not task["verifier_available"]:
            continue
        rules_passed.append("verifier_available")

        # Rule 8: Materials obtainable
        if not task.get("source_materials"):
            continue
        rules_passed.append("materials_obtainable")

        task["_selection_rules_passed"] = rules_passed
        task["_selection_keyword_counts"] = {
            "re_cut": count_keyword_matches(instr_text, RE_CUT_KEYWORDS),
            "selection": count_keyword_matches(instr_text, SELECTION_KEYWORDS),
            "reorg": count_keyword_matches(instr_text, REORG_KEYWORDS),
        }
        filtered.append(task)

    return filtered


def select_medium_above(tasks: list[dict]) -> dict | None:
    """Select a medium-above complexity task from the filtered set."""
    if not tasks:
        return None

    # Complexity proxy: sum of keyword match counts + instruction length category
    for t in tasks:
        kc = t["_selection_keyword_counts"]
        t["_complexity_score"] = (
            kc["re_cut"] + kc["selection"] + kc["reorg"]
            + (1 if t["instruction_length_chars"] > 2500 else 0)
            + (1 if t["output_requirements"].get("duration") != "unknown" else 0)
        )

    scores = sorted(t["_complexity_score"] for t in tasks)
    median_s = scores[len(scores) // 2]
    min_s = scores[0]
    max_s = scores[-1]

    # Medium-above = complexity >= median
    above = [t for t in tasks if t["_complexity_score"] >= median_s]
    above.sort(key=lambda t: (t["_complexity_score"], t["task_id"]))

    selected = above[len(above) // 2] if above else tasks[0]

    return {
        "selected_task": selected["task_id"],
        "benchmark": "AgenticVBench",
        "family": "repurpose",
        "selection_rules": selected["_selection_rules_passed"],
        "candidate_count": len(tasks),
        "complexity_range": {"min": min_s, "median": median_s, "max": max_s},
        "selected_complexity_score": selected["_complexity_score"],
        "reason": (
            f"Selected from {len(tasks)} candidates that pass all EDIT filters. "
            f"Complexity score {selected['_complexity_score']} is at/above "
            f"median ({median_s}) of range [{min_s}, {max_s}]."
        ),
    }


def load_instructions(tasks_root: Path) -> dict[str, str]:
    """Load instruction.md for each task."""
    instructions = {}
    for task_dir in sorted(tasks_root.iterdir()):
        if not task_dir.is_dir():
            continue
        instr_path = task_dir / "steps" / "solve" / "instruction.md"
        if instr_path.is_file():
            try:
                instructions[task_dir.name] = instr_path.read_text(encoding="utf-8")
            except Exception:
                instructions[task_dir.name] = ""
    return instructions


def main():
    parser = argparse.ArgumentParser(description="Select EDIT case from AgenticVBench Repurpose")
    parser.add_argument(
        "--candidates",
        default="evidence/case_selection/agentic_vbench_repurpose_candidates.json",
        help="Path to agentic_vbench_repurpose_candidates.json",
    )
    parser.add_argument(
        "--tasks-root",
        default="upstream/agentic_vbench/tasks_repurpose",
        help="Path to tasks/agentic_vbench_repurpose/ directory (for instruction text)",
    )
    parser.add_argument(
        "--output",
        default="evidence/case_selection/edit_selection.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    candidates_path = Path(args.candidates)
    tasks_root = Path(args.tasks_root)
    output = Path(args.output)

    if not candidates_path.is_file():
        print(f"Candidates file not found: {candidates_path}")
        sys.exit(1)

    with open(candidates_path) as f:
        data = json.load(f)

    instructions = load_instructions(tasks_root)

    filtered = filter_edit_cases(data["tasks"], instructions)
    if filtered:
        result = select_medium_above(filtered)
        result["status"] = "selected"
    else:
        result = {
            "benchmark": "AgenticVBench",
            "family": "repurpose",
            "selected_task": None,
            "status": "no_match",
            "reason": f"No tasks passed all EDIT filters from {data['total_tasks']} candidates.",
            "candidate_count": data["total_tasks"],
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"EDIT selection: {result.get('status', 'unknown')}")
    if result.get("selected_task"):
        print(f"  selected: {result['selected_task']}")
        print(f"  reason: {result['reason']}")
    else:
        print(f"  reason: {result.get('reason', 'unknown')}")
    print(f"  output: {output}")


if __name__ == "__main__":
    main()
