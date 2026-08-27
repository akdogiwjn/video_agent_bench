#!/usr/bin/env python3
"""DashScope VLM adapter — Qwen-VL visual understanding.

Uses the OpenAI-compatible DashScope endpoint to call Qwen-VL for image
understanding. This is a thin adapter: it executes the VLM call only.
It does NOT make content selection, editing, or planning decisions.

Environment:
    DASHSCOPE_API_KEY — required
    VLM_BASE_URL — optional (defaults to DashScope compatible-mode)
    VLM_MODEL — required (e.g. qwen-vl-max)

Usage:
    from tools.providers.dashscope_vlm import vlm_describe_image
    result = vlm_describe_image(image_path="/path/to/image.png", prompt="Describe this image")
"""
import base64
import os
import sys
from pathlib import Path

# Add project root to path for imports
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.providers.dashscope_client import (
    get_dashscope_api_key,
    get_dashscope_base_url,
)


def vlm_describe_image(image_path: str, prompt: str, model: str | None = None) -> str:
    """Send an image to Qwen-VL with a prompt and return the text response."""
    api_key = get_dashscope_api_key()
    if not api_key:
        return "ERROR: DASHSCOPE_API_KEY is not set"

    vlm_model = model or os.environ.get("VLM_MODEL", "")
    if not vlm_model:
        return "ERROR: VLM_MODEL is not set. Configure it in config/config.env"

    base_url = os.environ.get("VLM_BASE_URL", get_dashscope_base_url())

    try:
        from openai import OpenAI
    except ImportError:
        return "ERROR: openai package is not installed"

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    ext = Path(image_path).suffix.lstrip(".") or "png"
    client = OpenAI(api_key=api_key, base_url=base_url)

    response = client.chat.completions.create(
        model=vlm_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/{ext};base64,{img_b64}"}},
            ],
        }],
        max_tokens=1000,
    )
    return response.choices[0].message.content


def vlm_check_prompt_adherence(frame_paths: list[str], prompt: str, model: str | None = None) -> dict:
    """Check if video frames match the original prompt.

    Returns {"pass": bool, "detail": str, "method": "vlm"}.
    """
    api_key = get_dashscope_api_key()
    if not api_key or not frame_paths:
        return {"pass": False, "detail": "no DASHSCOPE_API_KEY or no frames", "method": "vlm_unavailable"}

    vlm_model = model or os.environ.get("VLM_MODEL", "")
    if not vlm_model:
        return {"pass": False, "detail": "VLM_MODEL not set", "method": "vlm_unavailable"}

    base_url = os.environ.get("VLM_BASE_URL", get_dashscope_base_url())

    try:
        from openai import OpenAI
    except ImportError:
        return {"pass": False, "detail": "openai package not installed", "method": "vlm_unavailable"}

    client = OpenAI(api_key=api_key, base_url=base_url)

    sample_indices = [0, len(frame_paths) // 2, -1] if len(frame_paths) >= 3 else [0]
    sample_frames = [frame_paths[i] for i in sample_indices]

    vlm_prompt = (
        f"The following is a video generation prompt:\n\n\"{prompt}\"\n\n"
        f"I will show you {len(sample_frames)} frames from a generated video. "
        f"Does the visual content of these frames match the prompt? "
        f"Answer with EXACTLY 'YES' or 'NO' on the first line, then a one-sentence reason."
    )

    content = [{"type": "text", "text": vlm_prompt}]
    for fp in sample_frames:
        with open(fp, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })

    try:
        response = client.chat.completions.create(
            model=vlm_model,
            messages=[{"role": "user", "content": content}],
            max_tokens=200,
        )
        answer = response.choices[0].message.content.strip()
        is_yes = answer.upper().startswith("YES")
        return {"pass": is_yes, "detail": f"VLM answer: {answer}", "method": "vlm"}
    except Exception as e:
        return {"pass": False, "detail": f"VLM error: {e}", "method": "vlm_error"}
