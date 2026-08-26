#!/usr/bin/env python3
"""Generate a source_manifest.json with SHA256 hashes for every file under a directory.

Usage:
    python3 tools/generate_manifest.py <root_dir> --benchmark <name> --repo <repo> --commit <sha> [--output <path>]

The manifest records the benchmark name, repository, commit, and a flat mapping
of relative file paths to their SHA256 hashes. Binary files (images, videos)
are hashed the same way as text files.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(root: Path) -> dict[str, str]:
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for filename in sorted(filenames):
            if filename == ".DS_Store":
                continue
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, root)
            files[rel] = sha256_file(full)
    return files


def main():
    parser = argparse.ArgumentParser(description="Generate source_manifest.json")
    parser.add_argument("root_dir", help="Root directory to hash")
    parser.add_argument("--benchmark", required=True, help="Benchmark name")
    parser.add_argument("--repo", required=True, help="Repository (owner/name)")
    parser.add_argument("--commit", required=True, help="Full commit SHA")
    parser.add_argument("--output", default=None, help="Output path (default: <root_dir>/source_manifest.json)")
    args = parser.parse_args()

    root = Path(args.root_dir).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    files = collect_files(root)
    manifest = {
        "benchmark": args.benchmark,
        "repository": args.repo,
        "commit": args.commit,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "files": dict(sorted(files.items())),
    }

    output = Path(args.output) if args.output else root / "source_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Manifest written to {output}")
    print(f"  benchmark: {args.benchmark}")
    print(f"  commit:    {args.commit}")
    print(f"  files:     {len(files)}")


if __name__ == "__main__":
    main()
