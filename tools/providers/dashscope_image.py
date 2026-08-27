#!/usr/bin/env python3
"""DashScope Wan2.7 Image adapter — image generation via DashScope native API.

Uses the DashScope native async task API for Wan image generation.
Endpoint: /api/v1/services/aigc/image-generation/generation

Environment:
    DASHSCOPE_API_KEY — required
    IMAGE_GEN_MODEL — required (e.g. wan2.7-image, wan2.7-image-pro)
    DASHSCOPE_NATIVE_BASE_URL — optional (default: https://dashscope.aliyuncs.com/api/v1)

Wan2.7 Image request uses the messages format:
    "input": {
        "messages": [
            {"role": "user", "content": [{"text": "prompt"}]}
        ]
    }
"""
import os
import sys
import time
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.providers.dashscope_client import get_dashscope_api_key, get_native_base_url


def generate_image(prompt: str, output_path: str, model: str | None = None,
                   size: str = "1024*1024", timeout: int = 300) -> dict:
    """Generate an image via DashScope Wan2.7 Image API.

    Args:
        prompt: Image generation prompt
        output_path: Where to save the generated image
        model: Model name (falls back to IMAGE_GEN_MODEL env var)
        size: Image size (e.g. "1024*1024", "720*1280")
        timeout: Maximum polling time in seconds

    Returns:
        {"success": bool, "output_path": str, "error": str, "task_id": str}
    """
    api_key = get_dashscope_api_key()
    if not api_key:
        return {"success": False, "error": "DASHSCOPE_API_KEY is not set",
                "output_path": "", "task_id": ""}

    image_model = model or os.environ.get("IMAGE_GEN_MODEL", "")
    if not image_model:
        return {"success": False, "error": "IMAGE_GEN_MODEL is not set",
                "output_path": "", "task_id": ""}

    base_url = get_native_base_url().rstrip("/")
    submit_url = f"{base_url}/services/aigc/image-generation/generation"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    # Wan2.7 uses messages format (not plain prompt)
    payload = {
        "model": image_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}]
                }
            ]
        },
        "parameters": {
            "size": size,
            "n": 1,
        },
    }

    # Submit task
    try:
        resp = requests.post(submit_url, headers=headers, json=payload, timeout=30)
        resp_data = resp.json()
    except Exception as e:
        return {"success": False, "error": f"Submit failed: {e}",
                "output_path": "", "task_id": ""}

    if resp.status_code != 200:
        return {"success": False,
                "error": f"Submit HTTP {resp.status_code}: {resp_data.get('message', resp_data)}",
                "output_path": "", "task_id": ""}

    task_id = resp_data.get("output", {}).get("task_id", "")
    if not task_id:
        return {"success": False, "error": f"No task_id in response: {resp_data}",
                "output_path": "", "task_id": ""}

    # Poll for result using native task API
    task_url = f"{base_url}/tasks/{task_id}"
    poll_headers = {"Authorization": f"Bearer {api_key}"}

    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(3)
        try:
            poll_resp = requests.get(task_url, headers=poll_headers, timeout=30)
            poll_data = poll_resp.json()
        except Exception:
            continue

        output = poll_data.get("output", {})
        status = output.get("task_status", "")
        if status == "SUCCEEDED":
            # Wan2.7 image results are in output.results[]
            results = output.get("results", [])
            if results:
                image_url = results[0].get("url", "") if isinstance(results[0], dict) else str(results[0])
                if image_url:
                    try:
                        img_resp = requests.get(image_url, timeout=60)
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        with open(output_path, "wb") as f:
                            f.write(img_resp.content)
                        return {"success": True, "output_path": output_path,
                                "error": "", "task_id": task_id}
                    except Exception as e:
                        return {"success": False, "error": f"Download failed: {e}",
                                "output_path": "", "task_id": task_id}
            return {"success": False, "error": "No image URL in results",
                    "output_path": "", "task_id": task_id}
        elif status == "FAILED":
            return {"success": False,
                    "error": f"Task failed: {output.get('message', 'unknown')}",
                    "output_path": "", "task_id": task_id}

    return {"success": False, "error": f"Timeout after {timeout}s",
            "output_path": "", "task_id": task_id}
