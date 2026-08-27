#!/usr/bin/env python3
"""DashScope API client — shared authentication and base URL resolution.

All DashScope adapters (VLM, image-gen, video-gen, omni) use this module
for consistent API key resolution and OpenAI-compatible client construction.

DashScope provides an OpenAI-compatible endpoint at:
    https://dashscope.aliyuncs.com/compatible-mode/v1

Environment variables:
    DASHSCOPE_API_KEY — required
    DASHSCOPE_BASE_URL — optional, defaults to the compatible-mode endpoint
"""
import os
import sys


def get_dashscope_api_key() -> str:
    """Return the DashScope API key or empty string."""
    return os.environ.get("DASHSCOPE_API_KEY", "")


def get_dashscope_base_url() -> str:
    """Return the DashScope base URL for OpenAI-compatible mode."""
    return os.environ.get("DASHSCOPE_BASE_URL",
                          "https://dashscope.aliyuncs.com/compatible-mode/v1")


def get_dashscope_client():
    """Construct and return an OpenAI-compatible client for DashScope.

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
    return OpenAI(api_key=api_key, base_url=get_dashscope_base_url())


def check_configured() -> dict:
    """Check if DashScope is properly configured. Does not print keys."""
    api_key = get_dashscope_api_key()
    base_url = get_dashscope_base_url()
    return {
        "configured": bool(api_key),
        "base_url": base_url,
        "api_key_present": bool(api_key),
    }


def get_model(model_env_var: str, default: str = "") -> str:
    """Read a model name from an environment variable."""
    return os.environ.get(model_env_var, default)
