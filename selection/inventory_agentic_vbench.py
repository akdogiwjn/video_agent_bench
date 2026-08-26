#!/usr/bin/env python3
"""Inventory AgenticVBench Repurpose tasks.

Scans the agentic_vbench_repurpose task family and extracts observable
metadata from each task directory. Does NOT guess or fabricate content —
fields that cannot be determined from the files are set to "unknown".

Expected task layout:
    tasks/agentic_vbench_repurpose/<task>/
    ├── environment/
    │   ├── Dockerfile
    │   └── brief.md
    ├── steps/
    │   └── solve/
    │       ├── instruction.md
    │       ├── tests/
    │       │   ├── aggregate.py
    │       │   ├── config.yaml
    │       │   ├── judge.py
    │       │   ├── rubric.json
    │       │   └── test.sh
    │       └── workdir/
    │           └── setup.sh
    └── task.toml

Usage:
    python3 selection/inventory_agentic_vbench.py --tasks-root <path> [--output <path>]

Output: evidence/case_selection/agentic_vbench_repurpose_candidates.json
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


def parse_task_toml(toml_path: Path) -> dict:
    """Parse task.toml and extract observable fields."""
    data = {}
    if not toml_path.is_file():
        return data
    try:
        if tomllib:
            with open(toml_path, "rb") as f:
                raw = tomllib.load(f)
        else:
            text = toml_path.read_text(encoding="utf-8")
            raw = _simple_toml_parse(text)
    except Exception as e:
        data["_parse_error"] = str(e)
        return data

    task = raw.get("task", {})
    metadata = raw.get("metadata", {})
    env = raw.get("environment", {})

    data["task_name"] = task.get("name", "unknown")
    data["difficulty"] = metadata.get("difficulty", "unknown")
    data["category"] = metadata.get("category", "unknown")
    data["tags"] = metadata.get("tags", [])
    data["source"] = metadata.get("source", "unknown")
    data["build_timeout_sec"] = env.get("build_timeout_sec", "unknown")
    data["cpus"] = env.get("cpus", "unknown")
    data["memory_mb"] = env.get("memory_mb", "unknown")
    data["storage_mb"] = env.get("storage_mb", "unknown")
    data["allow_internet"] = env.get("allow_internet", "unknown")

    steps = raw.get("steps", [])
    if steps:
        first_step = steps[0] if isinstance(steps, list) else steps
        agent_cfg = first_step.get("agent", {})
        verifier_cfg = first_step.get("verifier", {})
        data["agent_timeout_sec"] = agent_cfg.get("timeout_sec", "unknown")
        data["verifier_timeout_sec"] = verifier_cfg.get("timeout_sec", "unknown")

    return data


def _simple_toml_parse(text: str) -> dict:
    """Fallback TOML parser for Python < 3.11 without tomli."""
    import re
    result = {}
    current_section = result
    current_table = None

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            parts = line[1:-1].split(".")
            current_section = result
            for part in parts:
                current_section = current_section.setdefault(part, {})
            current_table = current_section
            continue
        if line.startswith("[["):
            parts = line[2:-2].split(".")
            current_section = result
            for part in parts:
                if part not in current_section:
                    current_section[part] = []
                if not isinstance(current_section[part], list):
                    current_section[part] = [current_section[part]]
                if not current_section[part] or not isinstance(current_section[part][-1], dict):
                    current_section[part].append({})
                current_section = current_section[part][-1]
            continue
        m = re.match(r'^(\w+)\s*=\s*(.*)$', line)
        if m and current_section is not None:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith('"') and val.endswith('"'):
                current_section[key] = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                current_section[key] = val[1:-1]
            elif val.lower() in ("true", "false"):
                current_section[key] = val.lower() == "true"
            elif val.replace(".", "").replace("-", "").isdigit():
                current_section[key] = float(val) if "." in val else int(val)
            else:
                current_section[key] = val

    return result


def parse_materials_url(dockerfile_path: Path) -> str:
    """Extract the HuggingFace materials URL from the task Dockerfile."""
    if not dockerfile_path.is_file():
        return "unknown"
    try:
        text = dockerfile_path.read_text(encoding="utf-8")
    except Exception:
        return "unknown"
    m = re.search(r"MATERIALS_URL=(\S+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(https://huggingface\.co/\S+)", text)
    if m:
        return m.group(1)
    return "unknown"


def parse_rubric_output_requirements(rubric_path: Path) -> dict:
    """Extract observable output requirements from the rubric.json."""
    reqs = {
        "vertical": "unknown",
        "duration": "unknown",
        "resolution": "unknown",
        "container_codec": "unknown",
        "audio_channels": "unknown",
        "sample_rate": "unknown",
    }
    if not rubric_path.is_file():
        return reqs
    try:
        with open(rubric_path, encoding="utf-8") as f:
            rubric = json.load(f)
    except Exception:
        return reqs

    items = rubric.get("items", [])
    for item in items:
        criterion = item.get("criterion", "")
        check = item.get("check", "")
        text = f"{criterion} {check}"

        if "1080" in text and "1920" in text:
            reqs["resolution"] = "1080x1920"
            reqs["vertical"] = True
        if re.search(r"\b75\s*s\b", text) or re.search(r"duration.*75", text, re.IGNORECASE):
            reqs["duration"] = "75s"
        if "h264" in text.lower() or "hevc" in text.lower() or "h.264" in text.lower():
            reqs["container_codec"] = "mp4/h264"
        if "stereo" in text.lower() or "channels=2" in text.lower():
            reqs["audio_channels"] = "2 (stereo)"
        if "44100" in text or "48000" in text:
            reqs["sample_rate"] = "44100 or 48000"

    return reqs


def scan_task(task_path: Path) -> dict | None:
    """Scan a single repurpose task directory."""
    if not task_path.is_dir():
        return None

    task_id = task_path.name
    toml_path = task_path / "task.toml"
    instruction_path = task_path / "steps" / "solve" / "instruction.md"
    brief_path = task_path / "environment" / "brief.md"
    dockerfile_path = task_path / "environment" / "Dockerfile"
    rubric_path = task_path / "steps" / "solve" / "tests" / "rubric.json"
    judge_path = task_path / "steps" / "solve" / "tests" / "judge.py"
    aggregate_path = task_path / "steps" / "solve" / "tests" / "aggregate.py"
    test_sh_path = task_path / "steps" / "solve" / "tests" / "test.sh"

    toml_data = parse_task_toml(toml_path)
    materials_url = parse_materials_url(dockerfile_path)
    output_reqs = parse_rubric_output_requirements(rubric_path)

    verifier_available = judge_path.is_file() and rubric_path.is_file()

    instruction_text = "unknown"
    if instruction_path.is_file():
        try:
            instruction_text = instruction_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    source_materials = []
    if materials_url != "unknown":
        source_materials.append({"type": "video", "url": materials_url, "expected_path": "/workspace/materials/source.mp4"})

    return {
        "task_id": task_id,
        "family": "repurpose",
        "instruction_path": str(instruction_path.relative_to(task_path.parent.parent.parent)) if instruction_path.is_file() else "unknown",
        "instruction_length_chars": len(instruction_text) if instruction_text != "unknown" else 0,
        "source_materials": source_materials,
        "source_duration_seconds": "unknown",
        "output_requirements": output_reqs,
        "verifier_available": verifier_available,
        "verifier_files": {
            "judge.py": judge_path.is_file(),
            "aggregate.py": aggregate_path.is_file(),
            "rubric.json": rubric_path.is_file(),
            "test.sh": test_sh_path.is_file(),
            "config.yaml": (task_path / "steps" / "solve" / "tests" / "config.yaml").is_file(),
        },
        "task_metadata": toml_data,
        "difficulty": toml_data.get("difficulty", "unknown"),
    }


def main():
    parser = argparse.ArgumentParser(description="Inventory AgenticVBench Repurpose tasks")
    parser.add_argument(
        "--tasks-root",
        required=True,
        help="Path to the tasks/agentic_vbench_repurpose/ directory",
    )
    parser.add_argument(
        "--output",
        default="evidence/case_selection/agentic_vbench_repurpose_candidates.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    tasks_root = Path(args.tasks_root).resolve()
    output = Path(args.output)

    result = {
        "benchmark": "AgenticVBench",
        "family": "repurpose",
        "tasks_root": str(tasks_root),
        "total_tasks": 0,
        "tasks": [],
        "notes": [],
    }

    if not tasks_root.is_dir():
        result["notes"].append(f"Tasks root does not exist: {tasks_root}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Tasks root not found: {tasks_root}")
        sys.exit(1)

    for task_dir in sorted(tasks_root.iterdir()):
        if task_dir.name in (".DS_Store",):
            continue
        if not task_dir.is_dir():
            continue
        task = scan_task(task_dir)
        if task:
            result["tasks"].append(task)
            result["total_tasks"] += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Scanned {tasks_root}")
    print(f"  total tasks: {result['total_tasks']}")
    print(f"  with verifier: {sum(1 for t in result['tasks'] if t['verifier_available'])}")
    print(f"  output: {output}")


if __name__ == "__main__":
    main()
