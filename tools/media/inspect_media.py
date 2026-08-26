#!/usr/bin/env python3
"""Inspect media files using ffprobe and print key metadata.

Usage:
    python3 tools/media/inspect_media.py <file> [--json]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def probe(filepath: str) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            filepath,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    return json.loads(result.stdout)


def summarize(probe_data: dict) -> dict:
    fmt = probe_data.get("format", {})
    streams = probe_data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    summary = {
        "filename": fmt.get("filename", ""),
        "format": fmt.get("format_name", ""),
        "duration_seconds": float(fmt.get("duration", 0)),
        "size_bytes": int(fmt.get("size", 0)),
    }

    if video_stream:
        summary["video"] = {
            "codec": video_stream.get("codec_name", ""),
            "width": video_stream.get("width", 0),
            "height": video_stream.get("height", 0),
            "fps": eval(video_stream.get("r_frame_rate", "0/1")) if "/" in video_stream.get("r_frame_rate", "0") else 0,
            "bit_rate": int(video_stream.get("bit_rate", 0)),
        }

    if audio_stream:
        summary["audio"] = {
            "codec": audio_stream.get("codec_name", ""),
            "channels": audio_stream.get("channels", 0),
            "sample_rate": int(audio_stream.get("sample_rate", 0)),
            "bit_rate": int(audio_stream.get("bit_rate", 0)),
        }

    return summary


def main():
    parser = argparse.ArgumentParser(description="Inspect media file metadata")
    parser.add_argument("file", help="Path to media file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not Path(args.file).is_file():
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    probe_data = probe(args.file)
    if "error" in probe_data:
        print(f"ERROR: {probe_data['error']}", file=sys.stderr)
        sys.exit(1)

    summary = summarize(probe_data)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"File:      {summary['filename']}")
        print(f"Format:    {summary['format']}")
        print(f"Duration:  {summary['duration_seconds']:.2f}s")
        print(f"Size:      {summary['size_bytes']:,} bytes")
        if "video" in summary:
            v = summary["video"]
            print(f"Video:     {v['codec']} {v['width']}x{v['height']} @ {v['fps']:.1f}fps")
        if "audio" in summary:
            a = summary["audio"]
            print(f"Audio:     {a['codec']} {a['channels']}ch @ {a['sample_rate']}Hz")


if __name__ == "__main__":
    main()
