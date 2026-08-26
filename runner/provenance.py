"""Provenance tracking for video_agent_bench runner.

Computes SHA256 hashes, verifies case files against manifests, and generates
run_manifest.json — the core of the evidence chain.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(filepath: str | Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_directory(root: Path, exclude: set[str] | None = None) -> dict[str, str]:
    """Compute SHA256 for every file under `root`, returning {rel_path: hash}."""
    exclude = exclude or set()
    files = {}
    root = Path(root)
    if not root.is_dir():
        return files
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude and d != "__pycache__")
        for fn in sorted(filenames):
            if fn in (".DS_Store",):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            files[rel] = sha256_file(full)
    return dict(sorted(files.items()))


def verify_case_manifest(case_dir: Path) -> tuple[bool, list[str]]:
    """Verify that case files match their recorded SHA256 in case_manifest.json."""
    manifest_path = case_dir / "case_manifest.json"
    if not manifest_path.is_file():
        return False, [f"case_manifest.json not found in {case_dir}"]

    with open(manifest_path) as f:
        manifest = json.load(f)

    errors = []
    for rel, expected_sha in manifest.get("files", {}).items():
        local_path = case_dir / rel
        if not local_path.is_file():
            errors.append(f"MISSING: {rel}")
            continue
        actual_sha = sha256_file(local_path)
        if actual_sha != expected_sha:
            errors.append(f"HASH MISMATCH: {rel} (expected {expected_sha[:16]}, got {actual_sha[:16]})")

    # Check materials status
    for name, info in manifest.get("materials_status", {}).items():
        expected_path = case_dir / info.get("expected_path", name)
        if info.get("status") == "pending_download" and not expected_path.is_file():
            errors.append(f"PENDING: {info.get('expected_path')} — download from {info.get('huggingface_url', 'unknown')}")

    return len(errors) == 0, errors


def build_run_manifest(
    benchmark: str,
    case_id: str,
    benchmark_commit: str,
    agent: str,
    agent_version: str,
    agent_model: str,
    docker_image: str,
    docker_image_id: str,
    task_sha256: str,
    input_sha256: dict[str, str],
    skills_sha256: dict[str, str],
    started_at: str,
    finished_at: str,
    agent_exit_code: int,
    case_source: str = "unknown",
    official_benchmark_case: bool = False,
    instruction_sha256: str = "",
    original_prompt_sha256: str = "",
    adaptation_sha256: str = "",
    verifier_sha256: str = "",
    benchmark_sources: dict | None = None,
    verifier_status: str = "unknown",
    verifier_pass: bool = False,
    verifier_reward: float = 0.0,
) -> dict:
    """Build the run_manifest.json structure with full provenance chain."""
    manifest = {
        "benchmark": benchmark,
        "case_id": case_id,
        "case_source": case_source,
        "official_benchmark_case": official_benchmark_case,
        "benchmark_commit": benchmark_commit,
        "agent": agent,
        "agent_version": agent_version,
        "agent_model": agent_model,
        "docker_image": docker_image,
        "docker_image_id": docker_image_id,
        "task_sha256": task_sha256,
        "instruction_sha256": instruction_sha256 or task_sha256,
        "original_prompt_sha256": original_prompt_sha256,
        "adaptation_sha256": adaptation_sha256,
        "input_sha256": input_sha256,
        "skills_sha256": skills_sha256,
        "verifier_sha256": verifier_sha256,
        "started_at": started_at,
        "finished_at": finished_at,
        "agent_exit_code": agent_exit_code,
        "verifier_status": verifier_status,
        "verifier_pass": verifier_pass,
        "verifier_reward": verifier_reward,
    }
    if benchmark_sources:
        manifest["benchmark_sources"] = benchmark_sources
    return manifest


def write_run_manifest(manifest: dict, output_path: Path):
    """Write run_manifest.json to the results directory."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
