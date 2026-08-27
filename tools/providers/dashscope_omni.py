#!/usr/bin/env python3
"""DashScope Qwen-Omni adapter — audio/video multimodal understanding.

Uses the DashScope OpenAI-compatible endpoint to call Qwen-Omni for
audio and video understanding. Qwen-Omni can process:
    - Images (same as Qwen-VL)
    - Audio (speech, music, environment sounds)
    - Video (frame sequences with audio)

Environment:
    DASHSCOPE_API_KEY — required
    OMNI_MODEL — required (e.g. qwen-omni-turbo)
    DASHSCOPE_BASE_URL — optional

Usage:
    from tools.providers.dashscope_omni import omni_describe_audio
    result = omni_describe_audio(audio_path="/path/to/audio.wav", prompt="Describe the audio")
"""
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.providers.dashscope_client import get_dashscope_api_key, get_dashscope_base_url


def _encode_file_base64(filepath: str, mime_type: str = "audio/wav") -> str:
    """Read a file and return a base64 data URL."""
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime_type};base64,{b64}"


def _get_omni_client():
    """Get the OpenAI-compatible client configured for DashScope Omni."""
    api_key = get_dashscope_api_key()
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set")
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package is not installed")
    base_url = os.environ.get("DASHSCOPE_BASE_URL", get_dashscope_base_url())
    return OpenAI(api_key=api_key, base_url=base_url)


def omni_describe_audio(audio_path: str, prompt: str, model: str | None = None) -> str:
    """Send an audio file to Qwen-Omni with a prompt and return text."""
    api_key = get_dashscope_api_key()
    if not api_key:
        return "ERROR: DASHSCOPE_API_KEY is not set"

    omni_model = model or os.environ.get("OMNI_MODEL", "")
    if not omni_model:
        return "ERROR: OMNI_MODEL is not set. Configure it in config/config.env"

    client = _get_omni_client()
    data_url = _encode_file_base64(audio_path, "audio/wav")

    response = client.chat.completions.create(
        model=omni_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio", "input_audio": {"data": data_url}},
            ],
        }],
        max_tokens=1000,
    )
    return response.choices[0].message.content


def omni_describe_video(video_path: str, prompt: str, model: str | None = None) -> str:
    """Send a video file to Qwen-Omni with a prompt and return text.

    Note: Qwen-Omni video support depends on the model's capabilities.
    For basic video frame understanding without audio, consider using
    dashscope_vlm.vlm_describe_image with extracted frames instead.
    """
    api_key = get_dashscope_api_key()
    if not api_key:
        return "ERROR: DASHSCOPE_API_KEY is not set"

    omni_model = model or os.environ.get("OMNI_MODEL", "")
    if not omni_model:
        return "ERROR: OMNI_MODEL is not set. Configure it in config/config.env"

    client = _get_omni_client()

    # For video, Qwen-Omni accepts video as base64 data URL
    ext = Path(video_path).suffix.lstrip(".").lower()
    mime_map = {"mp4": "video/mp4", "avi": "video/x-msvideo",
                "mov": "video/quicktime", "webm": "video/webm"}
    mime_type = mime_map.get(ext, "video/mp4")
    data_url = _encode_file_base64(video_path, mime_type)

    response = client.chat.completions.create(
        model=omni_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "video_url", "video_url": {"url": data_url}},
            ],
        }],
        max_tokens=1000,
    )
    return response.choices[0].message.content


def omni_judge_audio(audio_path: str, rubric_prompt: str, model: str | None = None) -> dict:
    """Use Qwen-Omni as an audio judge.

    Returns {"pass": bool, "detail": str, "method": "omni"}.
    """
    api_key = get_dashscope_api_key()
    if not api_key:
        return {"pass": False, "detail": "DASHSCOPE_API_KEY not set", "method": "omni_unavailable"}

    omni_model = model or os.environ.get("OMNI_MODEL", "")
    if not omni_model:
        return {"pass": False, "detail": "OMNI_MODEL not set", "method": "omni_unavailable"}

    try:
        answer = omni_describe_audio(audio_path, rubric_prompt, omni_model)
        is_yes = answer.strip().upper().startswith("YES")
        return {"pass": is_yes, "detail": f"Omni answer: {answer}", "method": "omni"}
    except Exception as e:
        return {"pass": False, "detail": f"Omni error: {e}", "method": "omni_error"}
