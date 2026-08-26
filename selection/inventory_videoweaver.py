#!/usr/bin/env python3
"""Inventory VideoWeaver dataset cases.

Scans a VideoWeaver dataset root for task categories and case folders,
extracting only observable metadata (file types, counts, rubric presence).
Does NOT guess or interpret task semantics.

Expected dataset layout (from VideoWeaver README):
    dataset/
    └── <task_category>/
        ├── skill_query.json
        ├── <case_id>/
        │   ├── *.txt          (instruction / prompt text)
        │   ├── *.png/.jpg ... (reference images)
        │   ├── *.mp4/.avi ... (reference videos)
        │   ├── *.mp3/.wav ... (reference audio)
        │   └── rubric_deterministic.json
        └── ...

Usage:
    python3 selection/inventory_videoweaver.py --dataset-root <path> [--output <path>]

Output: evidence/case_selection/videoweaver_candidates.json
"""
import argparse
import json
import os
import sys
from pathlib import Path

IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".aac", ".flac", ".m4a"}


def classify_file(filename: str) -> str | None:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".txt":
        return "text"
    if ext in IMG_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def scan_case(case_path: Path, category: str) -> dict | None:
    """Scan a single case directory and extract observable metadata."""
    if not case_path.is_dir():
        return None

    case_id = case_path.name
    txt_files = []
    img_files = []
    video_files = []
    audio_files = []
    has_rubric = False

    for entry in sorted(case_path.iterdir()):
        if entry.name == ".DS_Store":
            continue
        if not entry.is_file():
            continue
        if entry.name == "rubric_deterministic.json":
            has_rubric = True
            continue
        ftype = classify_file(entry.name)
        if ftype == "text":
            txt_files.append(entry.name)
        elif ftype == "image":
            img_files.append(entry.name)
        elif ftype == "video":
            video_files.append(entry.name)
        elif ftype == "audio":
            audio_files.append(entry.name)

    reference_files = img_files + video_files + audio_files
    modalities = set()
    if img_files:
        modalities.add("image")
    if video_files:
        modalities.add("video")
    if audio_files:
        modalities.add("audio")

    instruction = ""
    if txt_files:
        try:
            instruction = (case_path / txt_files[0]).read_text(encoding="utf-8").strip()
        except Exception:
            instruction = "unknown"

    reference_modalities = sorted(modalities) if modalities else []

    estimated_multimodal_complexity = (
        len(reference_modalities)
        + (1 if len(img_files) > 1 else 0)
        + (1 if len(video_files) > 1 else 0)
        + (1 if audio_files else 0)
    )

    return {
        "category": category,
        "case_id": case_id,
        "instruction": instruction[:500] if instruction else "",
        "reference_files": reference_files,
        "reference_modalities": reference_modalities,
        "has_deterministic_rubric": has_rubric,
        "required_output": "video",
        "estimated_multimodal_complexity": estimated_multimodal_complexity,
    }


def scan_category(category_path: Path) -> list[dict]:
    """Scan a task category directory for cases."""
    cases = []
    skill_query_path = category_path / "skill_query.json"
    skill_query = "unknown"
    if skill_query_path.is_file():
        try:
            with open(skill_query_path, encoding="utf-8") as f:
                sq = json.load(f)
                skill_query = sq.get("skill_query", "unknown")
        except Exception:
            pass

    for entry in sorted(category_path.iterdir()):
        if entry.name in (".DS_Store", "skill_query.json"):
            continue
        if entry.is_dir():
            case = scan_case(entry, category_path.name)
            if case:
                case["skill_query"] = skill_query[:500] if skill_query != "unknown" else "unknown"
                cases.append(case)
    return cases


def main():
    parser = argparse.ArgumentParser(description="Inventory VideoWeaver dataset cases")
    parser.add_argument(
        "--dataset-root",
        required=True,
        help="Path to the VideoWeaver dataset/ directory",
    )
    parser.add_argument(
        "--output",
        default="evidence/case_selection/videoweaver_candidates.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).resolve()
    output = Path(args.output)

    result = {
        "benchmark": "VideoWeaver",
        "dataset_root": str(dataset_root),
        "categories": [],
        "total_cases": 0,
        "cases": [],
        "notes": [],
    }

    if not dataset_root.is_dir():
        result["notes"].append(
            f"Dataset root does not exist: {dataset_root}. "
            "VideoWeaver dataset is not yet publicly released (see dataset/README.md)."
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Dataset root not found: {dataset_root}")
        print(f"Wrote {output} with 0 candidates.")
        sys.exit(0)

    for category_dir in sorted(dataset_root.iterdir()):
        if category_dir.name in (".DS_Store",):
            continue
        if not category_dir.is_dir():
            continue
        cases = scan_category(category_dir)
        if cases:
            result["categories"].append(category_dir.name)
            result["cases"].extend(cases)
            result["total_cases"] += len(cases)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Scanned {dataset_root}")
    print(f"  categories: {len(result['categories'])}")
    print(f"  total cases: {result['total_cases']}")
    print(f"  output: {output}")


if __name__ == "__main__":
    main()
