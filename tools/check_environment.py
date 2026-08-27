#!/usr/bin/env python3
"""Preflight environment checker for video_agent_bench.

Verifies that all required environment variables are configured before
running a case. Does NOT print API key values — only "configured" or "missing".

Usage:
    python3 tools/check_environment.py --case gen
    python3 tools/check_environment.py --case edit
"""
import argparse
import os
import sys
from pathlib import Path


def check_var(name: str, required: bool = True) -> dict:
    """Check if an environment variable is set."""
    val = os.environ.get(name, "")
    return {
        "name": name,
        "configured": bool(val),
        "required": required,
        "status": "configured" if val else ("missing" if required else "optional"),
    }


def check_gen() -> dict:
    """Check GEN case prerequisites."""
    checks = []

    # Agent LLM (DeepSeek)
    checks.append(check_var("DEEPSEEK_API_KEY"))
    checks.append(check_var("DEEPSEEK_BASE_URL", required=False))
    agent_model = os.environ.get("AGENT_MODEL", "")
    checks.append({"name": "AGENT_MODEL", "configured": bool(agent_model),
                    "required": True, "status": agent_model or "missing"})

    # VLM (DashScope Qwen-VL)
    checks.append(check_var("DASHSCOPE_API_KEY"))
    vlm_model = os.environ.get("VLM_MODEL", "")
    checks.append({"name": "VLM_MODEL", "configured": bool(vlm_model),
                    "required": True, "status": vlm_model or "missing"})
    checks.append(check_var("VLM_BASE_URL", required=False))

    # Image generation
    image_model = os.environ.get("IMAGE_GEN_MODEL", "")
    checks.append({"name": "IMAGE_GEN_MODEL", "configured": bool(image_model),
                    "required": True, "status": image_model or "missing"})

    # Video generation
    video_model = os.environ.get("VIDEO_GEN_MODEL", "")
    checks.append({"name": "VIDEO_GEN_MODEL", "configured": bool(video_model),
                    "required": True, "status": video_model or "missing"})

    return {"case": "gen", "checks": checks,
            "all_pass": all(c["configured"] for c in checks if c["required"])}


def check_edit() -> dict:
    """Check EDIT case prerequisites."""
    checks = []

    # Agent LLM (DeepSeek)
    checks.append(check_var("DEEPSEEK_API_KEY"))
    agent_model = os.environ.get("AGENT_MODEL", "")
    checks.append({"name": "AGENT_MODEL", "configured": bool(agent_model),
                    "required": True, "status": agent_model or "missing"})

    # VLM (DashScope Qwen-VL) for visual judge
    checks.append(check_var("DASHSCOPE_API_KEY"))
    vlm_model = os.environ.get("VLM_MODEL", "")
    checks.append({"name": "VLM_MODEL", "configured": bool(vlm_model),
                    "required": True, "status": vlm_model or "missing"})

    # Omni (DashScope Qwen-Omni) for audio judge
    omni_model = os.environ.get("OMNI_MODEL", "")
    checks.append({"name": "OMNI_MODEL", "configured": bool(omni_model),
                    "required": False, "status": omni_model or "not set (audio judge will be skipped)"})

    # EDIT verifier mode
    verifier_mode = os.environ.get("EDIT_VERIFIER_MODE", "adapted")
    checks.append({"name": "EDIT_VERIFIER_MODE", "configured": True,
                    "required": True, "status": verifier_mode})

    # If official mode, check Gemini + Anthropic
    if verifier_mode == "official":
        checks.append(check_var("GEMINI_API_KEY"))
        checks.append(check_var("ANTHROPIC_API_KEY"))
    else:
        checks.append({"name": "GEMINI_API_KEY", "configured": bool(os.environ.get("GEMINI_API_KEY")),
                        "required": False, "status": "not required (adapted mode)"})
        checks.append({"name": "ANTHROPIC_API_KEY", "configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
                        "required": False, "status": "not required (adapted mode)"})

    return {"case": "edit", "checks": checks,
            "all_pass": all(c["configured"] for c in checks if c["required"])}


def main():
    parser = argparse.ArgumentParser(description="Preflight environment checker")
    parser.add_argument("--case", required=True, choices=["gen", "edit"],
                        help="Case type to check")
    args = parser.parse_args()

    # Load config.env if it exists
    config_env = Path(__file__).resolve().parent.parent / "config" / "config.env"
    if config_env.is_file():
        with open(config_env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    if val and key not in os.environ:
                        os.environ[key] = val

    if args.case == "gen":
        result = check_gen()
    else:
        result = check_edit()

    print(f"=== Preflight Check: {result['case'].upper()} ===")
    for c in result["checks"]:
        status_str = "PASS" if c["configured"] else ("WARN" if not c["required"] else "FAIL")
        print(f"  {status_str}: {c['name']} = {c['status']}")

    print(f"\nOverall: {'PASS' if result['all_pass'] else 'FAIL'}")
    sys.exit(0 if result["all_pass"] else 1)


if __name__ == "__main__":
    main()
