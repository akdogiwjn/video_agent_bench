#!/usr/bin/env python3
"""Thin VLM (Vision Language Model) adapter for EDIT.

Provides a minimal, standardized interface for the agent to call a VLM
for visual understanding. This tool only executes the VLM call — it does
NOT make content selection, editing, or planning decisions.

Usage:
    python3 tools/media/vlm_understand.py --image <path> --prompt "Describe this image"
    python3 tools/media/vlm_understand.py --video <path> --prompt "Describe key moments"

Environment:
    ARK_API_KEY or OPENAI_API_KEY for VLM backend
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path


def call_vlm(image_path: str | None, video_path: str | None, prompt: str, model: str | None = None) -> str:
    """Call a VLM with an image or video and a prompt.

    Uses openai-compatible API (works with Volcengine ARK, OpenAI, etc.)
    """
    try:
        from openai import OpenAI
    except ImportError:
        return "ERROR: openai package not installed"

    api_key = os.environ.get("ARK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return "ERROR: No API key set (ARK_API_KEY or OPENAI_API_KEY)"

    base_url = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    if not os.environ.get("ARK_API_KEY"):
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    client = OpenAI(api_key=api_key, base_url=base_url)
    vlm_model = model or os.environ.get("VLM_MODEL", "doubao-1-5-vision-pro-32k-250115")

    content = [{"type": "text", "text": prompt}]

    if image_path:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        ext = Path(image_path).suffix.lstrip(".")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/{ext};base64,{img_b64}"}
        })
    elif video_path:
        # For video, extract first frame and send as image
        import subprocess
        import tempfile
        tmp = tempfile.mktemp(suffix=".png")
        subprocess.run(["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-q:v", "2", tmp],
                      capture_output=True, timeout=30)
        with open(tmp, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })

    response = client.chat.completions.create(
        model=vlm_model,
        messages=[{"role": "user", "content": content}],
        max_tokens=1000,
    )
    return response.choices[0].message.content


def main():
    parser = argparse.ArgumentParser(description="VLM understanding adapter")
    parser.add_argument("--image", default=None, help="Path to image file")
    parser.add_argument("--video", default=None, help="Path to video file")
    parser.add_argument("--prompt", required=True, help="Question/prompt for the VLM")
    parser.add_argument("--model", default=None, help="VLM model name")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not args.image and not args.video:
        print("ERROR: must provide --image or --video", file=sys.stderr)
        sys.exit(1)

    result = call_vlm(args.image, args.video, args.prompt, args.model)

    if args.json:
        print(json.dumps({"prompt": args.prompt, "response": result}, ensure_ascii=False))
    else:
        print(result)


if __name__ == "__main__":
    main()
