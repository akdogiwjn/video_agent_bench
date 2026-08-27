#!/usr/bin/env python3
"""DashScope Qwen-Omni adapter — audio/video multimodal understanding.

Uses the DashScope OpenAI-compatible endpoint to call Qwen-Omni for
audio and video understanding. Qwen-Omni can process:
    - Images (same as Qwen-VL)
    - Audio (speech, music, environment sounds)
    - Video (frame sequences with audio)

Important: Qwen-Omni requires streaming=True via OpenAI-compatible mode.

Environment:
    DASHSCOPE_API_KEY — required
    OMNI_MODEL — required (e.g. qwen3.5-omni-plus)
    DASHSCOPE_BASE_URL — optional (compatible-mode URL)

Audio input constraints:
    - Base64 input must be < 10 MB
    - Use ffmpeg to extract/compress audio before sending
    - input_audio.format is required (e.g. "wav", "mp3")

Usage:
    from tools.providers.dashscope_omni import omni_describe_audio
    result = omni_describe_audio(audio_path="/path/to/audio.wav", prompt="Describe the audio")
"""
import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.providers.dashscope_client import get_dashscope_api_key, get_compat_base_url


def _encode_file_base64(filepath: str, mime_type: str = "audio/wav") -> str:
    """Read a file and return a base64 data URL."""
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime_type};base64,{b64}"


def _get_file_size_mb(filepath: str) -> float:
    """Get file size in MB."""
    return os.path.getsize(filepath) / (1024 * 1024)


def _compress_audio(audio_path: str, max_size_mb: float = 8.0) -> str:
    """Compress audio to stay under the base64 size limit.

    Converts to mono MP3 16kHz which is sufficient for speech understanding.
    Returns path to compressed audio file.
    """
    size_mb = _get_file_size_mb(audio_path)
    if size_mb <= max_size_mb:
        return audio_path

    # Compress with ffmpeg to mono MP3
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path,
             "-ac", "1", "-ar", "16000",
             "-b:a", "64k",
             tmp],
            capture_output=True, timeout=60,
        )
        if os.path.exists(tmp) and _get_file_size_mb(tmp) <= max_size_mb:
            return tmp
        # If still too big, try lower bitrate
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path,
             "-ac", "1", "-ar", "8000",
             "-b:a", "32k",
             tmp],
            capture_output=True, timeout=60,
        )
        if os.path.exists(tmp):
            return tmp
    except Exception:
        pass
    return audio_path  # Return original if compression fails


def _get_audio_format(filepath: str) -> str:
    """Get audio format from file extension."""
    ext = Path(filepath).suffix.lstrip(".").lower()
    return ext if ext in ("wav", "mp3", "aac", "flac", "m4a") else "wav"


def _get_omni_client():
    """Get the OpenAI-compatible client configured for DashScope Omni."""
    api_key = get_dashscope_api_key()
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set")
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package is not installed")
    base_url = os.environ.get("DASHSCOPE_BASE_URL", get_compat_base_url())
    return OpenAI(api_key=api_key, base_url=base_url)


def omni_describe_audio(audio_path: str, prompt: str, model: str | None = None) -> str:
    """Send an audio file to Qwen-Omni with a prompt and return text.

    Uses streaming=True as required by Qwen-Omni OpenAI-compatible API.
    Compresses audio to stay under 10MB base64 limit.
    """
    api_key = get_dashscope_api_key()
    if not api_key:
        return "ERROR: DASHSCOPE_API_KEY is not set"

    omni_model = model or os.environ.get("OMNI_MODEL", "")
    if not omni_model:
        return "ERROR: OMNI_MODEL is not set. Configure it in config/config.env"

    # Compress audio if too large
    compressed_path = _compress_audio(audio_path, max_size_mb=8.0)
    audio_format = _get_audio_format(compressed_path)
    data_url = _encode_file_base64(compressed_path, f"audio/{audio_format}")

    client = _get_omni_client()

    # Qwen-Omni requires streaming=True via OpenAI-compatible mode
    response = client.chat.completions.create(
        model=omni_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio",
                 "input_audio": {"data": data_url, "format": audio_format}},
            ],
        }],
        max_tokens=1000,
        stream=True,
    )

    # Aggregate streaming response
    result = ""
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            result += chunk.choices[0].delta.content

    # Clean up compressed temp file if different from original
    if compressed_path != audio_path and os.path.exists(compressed_path):
        os.unlink(compressed_path)

    return result


def omni_describe_video(video_path: str, prompt: str, model: str | None = None) -> str:
    """Send a video file to Qwen-Omni with a prompt and return text.

    Extracts audio from video, compresses it, then sends to Qwen-Omni.
    For visual frame understanding, use dashscope_vlm with extracted frames instead.
    """
    api_key = get_dashscope_api_key()
    if not api_key:
        return "ERROR: DASHSCOPE_API_KEY is not set"

    omni_model = model or os.environ.get("OMNI_MODEL", "")
    if not omni_model:
        return "ERROR: OMNI_MODEL is not set. Configure it in config/config.env"

    # Extract audio from video
    tmp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path,
             "-ac", "1", "-ar", "16000",
             "-b:a", "64k",
             tmp_audio],
            capture_output=True, timeout=120,
        )
        if not os.path.exists(tmp_audio):
            return "ERROR: Could not extract audio from video"
    except Exception as e:
        return f"ERROR: Audio extraction failed: {e}"

    # Compress if needed
    compressed_path = _compress_audio(tmp_audio, max_size_mb=8.0)
    audio_format = _get_audio_format(compressed_path)
    data_url = _encode_file_base64(compressed_path, f"audio/{audio_format}")

    client = _get_omni_client()

    response = client.chat.completions.create(
        model=omni_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio",
                 "input_audio": {"data": data_url, "format": audio_format}},
            ],
        }],
        max_tokens=1000,
        stream=True,
    )

    result = ""
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            result += chunk.choices[0].delta.content

    # Cleanup
    if os.path.exists(tmp_audio):
        os.unlink(tmp_audio)
    if compressed_path != tmp_audio and os.path.exists(compressed_path):
        os.unlink(compressed_path)

    return result


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
