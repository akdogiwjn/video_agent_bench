#!/usr/bin/env python3
"""Adapted video-gen script — DashScope Wan Video backend.

This script replaces the original VideoWeaver video-gen script (which uses
Volcengine ARK/Seedance) with DashScope Wan Video as the generation backend.

Usage:
    python scripts/generate.py --prompt "A sunset" --output video.mp4 [--size 1280*720] [--duration 5]
    python scripts/generate.py --prompt "A sunset" --output-dir /workspace/output/videos

Environment:
    DASHSCOPE_API_KEY — required
    VIDEO_GEN_MODEL — required
    OUTPUT_DIR — optional (output directory fallback)
"""
import argparse
import os
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.providers.dashscope_video import generate_video


def main():
    parser = argparse.ArgumentParser(description="Generate video via DashScope Wan")
    parser.add_argument("--prompt", required=True, help="Video generation prompt")
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--size", default="1280*720", help="Video resolution (e.g. 1280*720, 720*1280)")
    parser.add_argument("--duration", default="5", help="Video duration in seconds")
    parser.add_argument("--model", default=None, help="Override VIDEO_GEN_MODEL")
    parser.add_argument("--timeout", type=int, default=600, help="Polling timeout in seconds")
    args = parser.parse_args()

    # Determine output path
    if args.output:
        output_path = args.output
    elif args.output_dir:
        output_path = os.path.join(args.output_dir, f"video_{os.getpid()}.mp4")
    else:
        output_dir = os.environ.get("OUTPUT_DIR", "/workspace/output")
        videos_dir = os.path.join(output_dir, "videos")
        os.makedirs(videos_dir, exist_ok=True)
        output_path = os.path.join(videos_dir, f"video_{os.getpid()}.mp4")

    print(f"Generating video: prompt='{args.prompt[:60]}...', output={output_path}")

    result = generate_video(
        prompt=args.prompt,
        output_path=output_path,
        model=args.model,
        size=args.size,
        duration=args.duration,
        timeout=args.timeout,
    )

    if result["success"]:
        print(f"SUCCESS: video saved to {result['output_path']}")
        print(f"task_id: {result['task_id']}")
    else:
        print(f"FAILED: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
