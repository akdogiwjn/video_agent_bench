#!/usr/bin/env python3
"""Select a representative GEN case from VBench prompt inventory.

GEN cases are now multi-benchmark-derived:
- Task content comes from VBench public prompt suite
- Agentic execution pattern comes from VideoWeaver
- Foundation skills come from VideoWeaver
- Methodology reference from MLPerf/MLCommons

Selection rules:
1. Prompt has a public benchmark source (VBench)
2. Content complexity moderate (not too short, not too long)
3. Not easily reducible to a single video-gen call
4. Suitable for long-form / multi-shot video organization
5. Can naturally produce multiple intermediate artifacts
6. Can naturally involve >= 2 media capabilities
7. Can be evaluated (deterministic format + quality checks)
8. Does not depend on unavailable private materials
9. Does not hardcode agent tool call sequence in the prompt

Usage:
    python3 selection/select_gen_case.py [--candidates <path>] [--output <path>]

Output: evidence/case_selection/gen_selection.json
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


# Complexity indicators — observable text patterns, not semantic guesses.
MULTI_SCENE_INDICATORS = [
    "transition", "meanwhile", "after", "before", "then", "later",
    "scene", "moment", "begins", "ends", "opens", "closes",
]
CHARACTER_INDICATORS = [
    "man", "woman", "boy", "girl", "child", "people", "couple",
    "family", "group", "friends", "person",
]
ACTION_INDICATORS = [
    "walks", "runs", "dances", "sits", "stands", "carries", "holds",
    "wearing", "looks", "turns", "moves", "plays",
]
ENVIRONMENT_INDICATORS = [
    "kitchen", "room", "street", "park", "beach", "forest",
    "city", "garden", "studio", "alley", "living",
]


def count_keyword_matches(text: str, keywords: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def compute_complexity_score(prompt: str) -> dict:
    """Compute observable complexity metrics for a prompt.

    These are NOT semantic quality judgments — they count observable
    text features that correlate with workload complexity.
    """
    word_count = len(prompt.split())
    char_count = len(prompt)

    multi_scene = count_keyword_matches(prompt, MULTI_SCENE_INDICATORS)
    characters = count_keyword_matches(prompt, CHARACTER_INDICATORS)
    actions = count_keyword_matches(prompt, ACTION_INDICATORS)
    environments = count_keyword_matches(prompt, ENVIRONMENT_INDICATORS)

    # Scene diversity proxy: distinct environment keywords
    text_lower = prompt.lower()
    distinct_envs = sum(1 for kw in ENVIRONMENT_INDICATORS if kw in text_lower)
    distinct_chars = sum(1 for kw in CHARACTER_INDICATORS if kw in text_lower)

    complexity = (
        multi_scene
        + (1 if distinct_chars >= 2 else 0)
        + (1 if distinct_envs >= 2 else 0)
        + (1 if actions >= 3 else 0)
        + (1 if word_count > 50 else 0)
        + (1 if word_count > 100 else 0)
    )

    return {
        "word_count": word_count,
        "char_count": char_count,
        "multi_scene_indicators": multi_scene,
        "character_indicators": characters,
        "action_indicators": actions,
        "environment_indicators": environments,
        "distinct_environments": distinct_envs,
        "distinct_characters": distinct_chars,
        "complexity_score": complexity,
    }


def filter_vbench_prompts(prompts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Apply GEN selection rules to VBench prompt candidates.

    Returns (filtered, excluded) where excluded has rejection reasons.
    """
    filtered = []
    excluded = []

    for prompt in prompts:
        reasons = []
        text = prompt["prompt"]

        # Rule 1: Public benchmark source — already true (from VBench)
        # Rule 2: Content complexity moderate
        word_count = len(text.split())
        if word_count < 10:
            reasons.append("too_short")
        if word_count > 200:
            reasons.append("too_long")

        # Rule 3: Not easily reducible to single video-gen
        # Prefer longer prompts (gpt_enhanced_longer) as they have more detail
        if prompt["prompt_type"] == "original" and word_count < 15:
            reasons.append("likely_single_call")

        # Rule 4: Suitable for long-form / multi-shot
        complexity = compute_complexity_score(text)
        if complexity["multi_scene_indicators"] == 0 and complexity["distinct_characters"] <= 1:
            reasons.append("low_scene_diversity")

        # Rule 7: Can be evaluated (all VBench prompts can — format + quality)
        # Rule 8: No private materials needed (VBench prompts are text-only)
        # Rule 9: Does not hardcode tool sequence (VBench prompts describe content, not process)

        if reasons:
            excluded.append({
                "prompt_id": prompt["prompt_id"],
                "category": prompt["category"],
                "prompt_type": prompt["prompt_type"],
                "exclusion_reasons": reasons,
            })
        else:
            prompt["_complexity"] = complexity
            prompt["_selection_rules_passed"] = [
                "public_benchmark_source",
                "moderate_complexity",
                "not_single_call",
                "scene_diversity",
                "evaluable",
                "no_private_materials",
                "no_hardcoded_workflow",
            ]
            filtered.append(prompt)

    return filtered, excluded


def select_best_candidate(filtered: list[dict]) -> dict | None:
    """Select the best GEN case candidate from the filtered set.

    Prefers gpt_enhanced_longer prompts (richer detail → better agent workload).
    Among those, picks medium-above complexity.
    """
    if not filtered:
        return None

    # Prefer gpt_enhanced_longer prompts
    longer = [p for p in filtered if p["prompt_type"] == "gpt_enhanced_longer"]
    pool = longer if longer else filtered

    scores = sorted(p["_complexity"]["complexity_score"] for p in pool)
    median_s = scores[len(scores) // 2]
    min_s = scores[0]
    max_s = scores[-1]

    # Medium-above = complexity >= median
    above = [p for p in pool if p["_complexity"]["complexity_score"] >= median_s]
    above.sort(key=lambda p: (p["_complexity"]["complexity_score"], p["prompt_id"]))

    selected = above[len(above) // 2] if above else pool[0]

    return {
        "selected_prompt_id": selected["prompt_id"],
        "selected_category": selected["category"],
        "selected_prompt_type": selected["prompt_type"],
        "selected_prompt": selected["prompt"],
        "selected_prompt_sha256": selected["sha256"],
        "case_source": "multi-benchmark-derived",
        "task_content_source": "VBench",
        "agentic_execution_basis": "VideoWeaver",
        "methodology_basis": "MLPerf",
        "official_benchmark_case": False,
        "selection_rules": selected["_selection_rules_passed"],
        "candidate_count": len(filtered),
        "excluded_count": 0,  # filled in main
        "complexity_range": {"min": min_s, "median": median_s, "max": max_s},
        "selected_complexity_score": selected["_complexity"]["complexity_score"],
        "selected_complexity_detail": selected["_complexity"],
        "reason": (
            f"Selected from {len(filtered)} candidates that pass all GEN filters "
            f"({len(pool)} gpt_enhanced_longer prompts in selection pool). "
            f"Complexity score {selected['_complexity']['complexity_score']} is at/above "
            f"median ({median_s}) of range [{min_s}, {max_s}]. "
            f"Prompt source: VBench commit {selected['source_commit'][:12]}."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Select GEN case from VBench prompt inventory")
    parser.add_argument(
        "--candidates",
        default="evidence/case_selection/vbench_candidates.json",
        help="Path to vbench_candidates.json",
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
            "case_source": "multi-benchmark-derived",
            "selected_prompt_id": None,
            "status": "error",
            "reason": f"Candidates file not found: {candidates_path}",
        }
    else:
        with open(candidates_path) as f:
            data = json.load(f)

        filtered, excluded = filter_vbench_prompts(data["prompts"])
        if filtered:
            result = select_best_candidate(filtered)
            result["status"] = "selected"
            result["excluded_count"] = len(excluded)
            result["excluded_summary"] = {
                "total_excluded": len(excluded),
                "reasons": {},
            }
            for ex in excluded:
                for r in ex["exclusion_reasons"]:
                    result["excluded_summary"]["reasons"][r] = (
                        result["excluded_summary"]["reasons"].get(r, 0) + 1
                    )
        else:
            result = {
                "case_source": "multi-benchmark-derived",
                "selected_prompt_id": None,
                "status": "no_match",
                "reason": f"No prompts passed all GEN filters from {data['total_prompts']} candidates.",
                "candidate_count": 0,
            }

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"GEN selection: {result.get('status', 'unknown')}")
    if result.get("selected_prompt_id"):
        print(f"  selected: {result['selected_prompt_id']}")
        print(f"  category: {result['selected_category']}")
        print(f"  type:     {result['selected_prompt_type']}")
        print(f"  reason:   {result['reason']}")
    else:
        print(f"  reason: {result.get('reason', 'unknown')}")
    print(f"  output: {output}")


if __name__ == "__main__":
    main()
