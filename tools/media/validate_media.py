#!/usr/bin/env python3
"""Validate that a media file meets expected output requirements.

Checks format, resolution, duration, codec, and audio properties
against a specification (e.g. from AgenticVBench rubric).

Usage:
    python3 tools/media/validate_media.py <file> --spec <json>
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def probe(filepath: str) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", filepath],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    return json.loads(result.stdout)


def validate(filepath: str, spec: dict) -> dict:
    probe_data = probe(filepath)
    if "error" in probe_data:
        return {"pass": False, "error": probe_data["error"]}

    streams = probe_data.get("streams", [])
    fmt = probe_data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})

    checks = {}

    # Resolution
    if "resolution" in spec:
        expected = spec["resolution"]
        actual = f"{video.get('width', 0)}x{video.get('height', 0)}"
        checks["resolution"] = {"expected": expected, "actual": actual, "pass": actual == expected}

    # Duration
    if "duration" in spec:
        try:
            actual_dur = float(fmt.get("duration", 0))
            expected_dur = spec["duration"]
            tol = spec.get("duration_tolerance", 0.1)
            checks["duration"] = {
                "expected": expected_dur,
                "actual": round(actual_dur, 2),
                "pass": abs(actual_dur - expected_dur) <= tol,
            }
        except (ValueError, TypeError):
            checks["duration"] = {"expected": spec["duration"], "actual": "unknown", "pass": False}

    # Codec
    if "video_codec" in spec:
        actual_codec = video.get("codec_name", "")
        expected_codecs = spec["video_codec"] if isinstance(spec["video_codec"], list) else [spec["video_codec"]]
        checks["video_codec"] = {
            "expected": expected_codecs,
            "actual": actual_codec,
            "pass": actual_codec in expected_codecs,
        }

    # Audio channels
    if "audio_channels" in spec:
        actual_ch = audio.get("channels", 0)
        checks["audio_channels"] = {
            "expected": spec["audio_channels"],
            "actual": actual_ch,
            "pass": actual_ch == spec["audio_channels"],
        }

    # Sample rate
    if "sample_rate" in spec:
        expected_rates = spec["sample_rate"] if isinstance(spec["sample_rate"], list) else [spec["sample_rate"]]
        actual_rate = int(audio.get("sample_rate", 0))
        checks["sample_rate"] = {
            "expected": expected_rates,
            "actual": actual_rate,
            "pass": actual_rate in expected_rates,
        }

    all_pass = all(c.get("pass", False) for c in checks.values()) if checks else True

    return {"pass": all_pass, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description="Validate media file against spec")
    parser.add_argument("file", help="Path to media file")
    parser.add_argument("--spec", required=True, help="Path to JSON spec file")
    args = parser.parse_args()

    if not Path(args.file).is_file():
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    with open(args.spec) as f:
        spec = json.load(f)

    result = validate(args.file, spec)

    print(f"=== Media Validation ===")
    print(f"  file: {args.file}")
    for name, check in result["checks"].items():
        status = "PASS" if check["pass"] else "FAIL"
        print(f"  {status}: {name} (expected={check['expected']}, actual={check['actual']})")
    print(f"\nOverall: {'PASS' if result['pass'] else 'FAIL'}")

    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
