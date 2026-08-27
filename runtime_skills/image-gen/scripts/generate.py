#!/usr/bin/env python3
"""Adapted image-gen script — DashScope Wan Image backend.

This script replaces the original VideoWeaver image-gen script (which uses
Volcengine ARK/Seedream) with DashScope Wan Image as the generation backend.

Usage:
    python scripts/generate.py --prompt "A sunset" --output image.png [--size 1024*1024]
    python scripts/generate.py --prompt "A sunset" --output-dir /workspace/output/images

Environment:
    DASHSCOPE_API_KEY — required
    IMAGE_GEN_MODEL — required
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

from tools.providers.dashscope_image import generate_image


def main():
    parser = argparse.ArgumentParser(description="Generate image via DashScope Wan")
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--size", default="1024*1024", help="Image size (e.g. 1024*1024, 720*1280)")
    parser.add_argument("--model", default=None, help="Override IMAGE_GEN_MODEL")
    parser.add_argument("--timeout", type=int, default=300, help="Polling timeout in seconds")
    args = parser.parse_args()

    # Determine output path
    if args.output:
        output_path = args.output
    elif args.output_dir:
        output_path = os.path.join(args.output_dir, f"image_{os.getpid()}.png")
    else:
        output_dir = os.environ.get("OUTPUT_DIR", "/workspace/output")
        images_dir = os.path.join(output_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        output_path = os.path.join(images_dir, f"image_{os.getpid()}.png")

    print(f"Generating image: prompt='{args.prompt[:60]}...', output={output_path}")

    result = generate_image(
        prompt=args.prompt,
        output_path=output_path,
        model=args.model,
        size=args.size,
        timeout=args.timeout,
    )

    if result["success"]:
        print(f"SUCCESS: image saved to {result['output_path']}")
        print(f"task_id: {result['task_id']}")
    else:
        print(f"FAILED: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
