#!/usr/bin/env python3
"""Extract frames from a video file.

Usage:
    python3 tools/media/extract_frames.py <video> --output <dir> [--interval <seconds>] [--count <n>]
"""
import argparse
import subprocess
import sys
from pathlib import Path


def extract_frames(video: str, output_dir: str, interval: float = 0, count: int = 0) -> list[str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-i", video]

    if count > 0:
        cmd.extend(["-vf", f"fps={count}/{get_duration(video)}"])
    elif interval > 0:
        cmd.extend(["-vf", f"fps=1/{interval}"])
    else:
        cmd.extend(["-vf", "fps=1"])

    output_pattern = str(output_dir / "frame_%05d.png")
    cmd.extend([output_pattern])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    frames = sorted(str(f) for f in output_dir.glob("frame_*.png"))
    return frames


def get_duration(video: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", video],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 1.0


def main():
    parser = argparse.ArgumentParser(description="Extract frames from video")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--interval", type=float, default=0, help="Extract one frame every N seconds")
    parser.add_argument("--count", type=int, default=0, help="Extract exactly N frames")
    args = parser.parse_args()

    if not Path(args.video).is_file():
        print(f"ERROR: video not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    frames = extract_frames(args.video, args.output, args.interval, args.count)
    print(f"Extracted {len(frames)} frames to {args.output}")
    for f in frames:
        print(f"  {f}")


if __name__ == "__main__":
    main()
