#!/usr/bin/env python3
"""DashScope API client — shared authentication and base URL resolution.

DashScope has two API surfaces:
1. OpenAI-compatible mode (for Qwen-VL, Qwen-Omni):
   DASHSCOPE_COMPAT_BASE_URL = https://dashscope.aliyuncs.com/compatible-mode/v1

2. Native async task API (for Wan Image/Video generation):
   DASHSCOPE_NATIVE_BASE_URL = https://dashscope.aliyuncs.com/api/v1

Environment variables:
    DASHSCOPE_API_KEY — required for all DashScope calls
    DASHSCOPE_BASE_URL — optional, overrides compatible-mode URL
    DASHSCOPE_NATIVE_BASE_URL — optional, overrides native API URL
"""
import os
import sys


def get_dashscope_api_key() -> str:
    """Return the DashScope API key or empty string."""
    return os.environ.get("DASHSCOPE_API_KEY", "")


def get_compat_base_url() -> str:
    """Return the OpenAI-compatible base URL (for Qwen-VL, Qwen-Omni)."""
    return os.environ.get("DASHSCOPE_BASE_URL",
                          os.environ.get("DASHSCOPE_COMPAT_BASE_URL",
                                         "https://dashscope.aliyuncs.com/compatible-mode/v1"))


def get_native_base_url() -> str:
    """Return the native DashScope API base URL (for Wan Image/Video)."""
    return os.environ.get("DASHSCOPE_NATIVE_BASE_URL",
                          "https://dashscope.aliyuncs.com/api/v1")


# Backward-compatible alias
def get_dashscope_base_url() -> str:
    """Return the OpenAI-compatible base URL (backward compat)."""
    return get_compat_base_url()


def get_dashscope_client():
    """Construct and return an OpenAI-compatible client for DashScope.

    Uses the compatible-mode endpoint (for Qwen-VL, Qwen-Omni).
    Raises RuntimeError if DASHSCOPE_API_KEY is not set.
    """
    api_key = get_dashscope_api_key()
    if not api_key:
        raise RuntimeError(
            "DASHSCOPE_API_KEY is not set. "
            "Configure it in config/config.env."
        )
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "openai package is not installed. "
            "Run: pip install openai"
        )
    return OpenAI(api_key=api_key, base_url=get_compat_base_url())


def check_configured() -> dict:
    """Check if DashScope is properly configured. Does not print keys."""
    api_key = get_dashscope_api_key()
    return {
        "configured": bool(api_key),
        "compat_base_url": get_compat_base_url(),
        "native_base_url": get_native_base_url(),
        "api_key_present": bool(api_key),
    }


def get_model(model_env_var: str, default: str = "") -> str:
    """Read a model name from an environment variable."""
    return os.environ.get(model_env_var, default)
