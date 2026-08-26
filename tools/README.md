# tools/

Reusable utilities for the video_agent_bench project.

## generate_manifest.py

Generate a `source_manifest.json` with SHA256 hashes for every file under a directory.

```bash
python3 tools/generate_manifest.py <root_dir> --benchmark <name> --repo <owner/name> --commit <sha> [--output <path>]
```

## verify_milestone1.py

Acceptance check for Milestone 1: prints both benchmark commits, scans VideoWeaver cases, scans 36 Repurpose tasks, and verifies source manifests.

```bash
python3 tools/verify_milestone1.py
```

## media/ (Milestone 4+)

Media inspection and validation utilities, created in later milestones.
