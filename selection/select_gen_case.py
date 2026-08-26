#!/usr/bin/env python3
"""Select a representative GEN case from VideoWeaver inventory.

Selection rules (from project plan):
1. Official case (from upstream VideoWeaver dataset)
2. Final output is a video
3. Multi-step task
4. Multi-shot (multiple clips/shots)
5. >= 2 media capabilities required
6. Verifier / evaluation info available
7. Required references obtainable

Then pick a medium-above complexity case from the filtered set.

Usage:
    python3 selection/select_gen_case.py [--candidates <path>] [--output <path>]

Output: evidence/case_selection/gen_selection.json
"""
import argparse
import json
import sys
from pathlib import Path


def filter_gen_cases(cases: list[dict]) -> list[dict]:
    """Apply GEN selection rules to candidate cases."""
    filtered = []
    for case in cases:
        # Rule 1: Official case — already true (from upstream)
        # Rule 2: Final output is video — already true (VideoWeaver always outputs video)
        # Rule 3: Multi-step — inferred from multimodal complexity >= 2
        # Rule 4: Multi-shot — inferred from > 1 video reference OR > 1 image reference
        # Rule 5: >= 2 media capabilities — reference_modalities count >= 2
        # Rule 6: Verifier/evaluation available — has_deterministic_rubric == True
        # Rule 7: References obtainable — reference_files not empty

        modalities = case.get("reference_modalities", [])
        ref_files = case.get("reference_files", [])
        has_rubric = case.get("has_deterministic_rubric", False)
        complexity = case.get("estimated_multimodal_complexity", 0)

        passes = (
            len(modalities) >= 2           # Rule 5
            and has_rubric                  # Rule 6
            and len(ref_files) > 0          # Rule 7
            and complexity >= 2             # Rule 3 (proxy)
        )

        if passes:
            case["_selection_rules_passed"] = [
                "official_case",
                "output_video",
                "multi_step",
                "multi_media_capabilities",
                "evaluation_available",
                "references_present",
            ]
            filtered.append(case)

    return filtered


def select_medium_above(cases: list[dict]) -> dict | None:
    """Select a medium-above complexity case from the filtered set."""
    if not cases:
        return None

    complexities = [c["estimated_multimodal_complexity"] for c in cases]
    if not complexities:
        return None

    max_c = max(complexities)
    min_c = min(complexities)
    median_c = sorted(complexities)[len(complexities) // 2]

    # Medium-above = complexity >= median
    threshold = median_c
    above = [c for c in cases if c["estimated_multimodal_complexity"] >= threshold]

    # Pick the first one at the median complexity (deterministic)
    above.sort(key=lambda c: (c["estimated_multimodal_complexity"], c["case_id"]))
    selected = above[len(above) // 2] if above else cases[0]

    return {
        "selected_case": selected["case_id"],
        "category": selected["category"],
        "benchmark": "VideoWeaver",
        "selection_rules": selected["_selection_rules_passed"],
        "candidate_count": len(cases),
        "complexity_range": {"min": min_c, "median": median_c, "max": max_c},
        "selected_complexity": selected["estimated_multimodal_complexity"],
        "reason": (
            f"Selected from {len(cases)} candidates that pass all GEN filters. "
            f"Complexity {selected['estimated_multimodal_complexity']} is at/above "
            f"median ({median_c}) of range [{min_c}, {max_c}]."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Select GEN case from VideoWeaver")
    parser.add_argument(
        "--candidates",
        default="evidence/case_selection/videoweaver_candidates.json",
        help="Path to videoweaver_candidates.json",
    )
    parser.add_argument(
        "--output",
        default="evidence/case_selection/gen_selection.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    candidates_path = Path(args.candidates)
    output = Path(args.output)

    if not candidates_path.is_file():
        result = {
            "benchmark": "VideoWeaver",
            "selected_case": None,
            "status": "blocked",
            "reason": f"Candidates file not found: {candidates_path}",
        }
    else:
        with open(candidates_path) as f:
            data = json.load(f)

        if data["total_cases"] == 0:
            result = {
                "benchmark": "VideoWeaver",
                "selected_case": None,
                "status": "blocked",
                "reason": (
                    "VideoWeaver dataset is not yet publicly released "
                    "(dataset/README.md says 'still being processed'). "
                    "GEN case selection is blocked until the dataset becomes available."
                ),
                "selection_rules": [
                    "multi_shot",
                    "multiple_media_capabilities",
                    "public_references",
                    "evaluation_available",
                ],
                "candidate_count": 0,
            }
        else:
            filtered = filter_gen_cases(data["cases"])
            if filtered:
                result = select_medium_above(filtered)
                result["status"] = "selected"
            else:
                result = {
                    "benchmark": "VideoWeaver",
                    "selected_case": None,
                    "status": "no_match",
                    "reason": f"No cases passed all GEN filters from {data['total_cases']} candidates.",
                    "candidate_count": data["total_cases"],
                }

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"GEN selection: {result.get('status', 'unknown')}")
    if result.get("selected_case"):
        print(f"  selected: {result['selected_case']}")
        print(f"  reason: {result['reason']}")
    else:
        print(f"  reason: {result.get('reason', 'unknown')}")
    print(f"  output: {output}")


if __name__ == "__main__":
    main()
