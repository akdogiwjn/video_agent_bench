#!/usr/bin/env python3
"""Download and freeze case materials (e.g. EDIT source.mp4).

Reads case_manifest.json to find materials with status "pending_download"
or "frozen", downloads from the recorded URL, computes SHA256, and verifies
it matches the manifest.

Usage:
    python3 tools/fetch_case_materials.py --case edit
    python3 tools/fetch_case_materials.py --case edit --force
"""
import argparse
import hashlib
import json
import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(filepath: str | Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> bool:
    """Download a file using curl with retry and resume support."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["curl", "--fail", "--location",
             "--retry", "5", "--retry-delay", "3",
             "--continue-at", "-",
             "--max-time", "3600",
             "-o", str(dest), url],
            timeout=3700,
        )
        return result.returncode == 0 and dest.is_file() and dest.stat().st_size > 0
    except Exception as e:
        print(f"  ERROR: download failed: {e}", file=sys.stderr)
        return False


def try_mirrors(url: str, dest: Path) -> bool:
    """Try original URL, then hf-mirror.com for HuggingFace URLs."""
    if download(url, dest):
        return True

    # Try hf-mirror for HuggingFace URLs
    if "huggingface.co" in url:
        mirror_url = url.replace("huggingface.co", "hf-mirror.com")
        print(f"  Trying mirror: {mirror_url}")
        if download(mirror_url, dest):
            return True

    return False


def fetch_case_materials(case_type: str, force: bool = False) -> bool:
    """Download and verify case materials."""
    case_dir = ROOT / "cases" / case_type

    # Find case manifest
    manifest_path = case_dir / "case_manifest.json"
    if not manifest_path.is_file():
        # Try subdirectory layout
        for d in case_dir.iterdir():
            if d.is_dir() and (d / "case_manifest.json").is_file():
                case_dir = d
                manifest_path = d / "case_manifest.json"
                break

    if not manifest_path.is_file():
        print(f"ERROR: no case_manifest.json found under {case_dir}", file=sys.stderr)
        return False

    with open(manifest_path) as f:
        manifest = json.load(f)

    case_id = manifest.get("case_id", "unknown")
    print(f"=== Fetching materials for {case_type}/{case_id} ===")

    all_ok = True

    # Check "materials" (new format) and "materials_status" (old format)
    materials = manifest.get("materials", {})
    materials_status = manifest.get("materials_status", {})

    # Combine both formats
    all_materials = {}
    for name, info in materials.items():
        all_materials[name] = info
    for name, info in materials_status.items():
        if name not in all_materials:
            all_materials[name] = info

    if not all_materials:
        print("  No materials to fetch.")
        return True

    for name, info in all_materials.items():
        expected_path = info.get("path", info.get("expected_path", f"materials/{name}"))
        dest = case_dir / expected_path
        expected_sha = info.get("sha256", "")
        url = info.get("url", info.get("source", info.get("huggingface_url", "")))
        status = info.get("status", "unknown")

        print(f"\n  Material: {name}")
        print(f"    expected_path: {expected_path}")
        print(f"    status: {status}")
        print(f"    url: {url}")

        if dest.is_file() and not force:
            actual_sha = sha256_file(dest)
            if expected_sha and actual_sha == expected_sha:
                print(f"    OK: already present and SHA256 verified")
                continue
            elif not expected_sha:
                print(f"    OK: already present (no SHA256 to verify)")
                continue
            else:
                print(f"    SHA256 MISMATCH — re-downloading")
                dest.unlink()

        if not url:
            print(f"    ERROR: no download URL recorded", file=sys.stderr)
            all_ok = False
            continue

        print(f"    Downloading...")
        if not try_mirrors(url, dest):
            print(f"    ERROR: download failed", file=sys.stderr)
            all_ok = False
            continue

        actual_sha = sha256_file(dest)
        print(f"    Downloaded: {dest.stat().st_size:,} bytes")
        print(f"    SHA256: {actual_sha}")

        if expected_sha:
            if actual_sha == expected_sha:
                print(f"    OK: SHA256 verified")
            else:
                print(f"    ERROR: SHA256 mismatch!", file=sys.stderr)
                print(f"      expected: {expected_sha}", file=sys.stderr)
                print(f"      actual:   {actual_sha}", file=sys.stderr)
                all_ok = False
        else:
            print(f"    WARNING: no expected SHA256 in manifest — skipping verification")

    print(f"\n{'All materials OK' if all_ok else 'Some materials failed'}")
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Download and freeze case materials")
    parser.add_argument("--case", required=True, choices=["gen", "edit"],
                        help="Case type")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if already present")
    args = parser.parse_args()

    ok = fetch_case_materials(args.case, args.force)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
