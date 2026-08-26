#!/usr/bin/env python3
"""Thin ASR (Automatic Speech Recognition) adapter for EDIT.

Provides a minimal, standardized interface for the agent to transcribe
audio from a media file. This tool only executes the ASR call — it does
NOT make content selection, editing, or planning decisions.

Uses Whisper (pre-cached in Docker image) for local transcription.

Usage:
    python3 tools/media/asr_transcribe.py <media-file> [--output <json|text>]

Output: transcribed text with timestamps
"""
import argparse
import json
import os
import sys
from pathlib import Path


def transcribe(filepath: str, model_name: str = "base") -> dict:
    """Transcribe audio from a media file using Whisper.

    Returns dict with segments (start, end, text) and full text.
    """
    try:
        import whisper
    except ImportError:
        return {"error": "openai-whisper not installed"}

    model = whisper.load_model(model_name, device="cpu")
    result = model.transcribe(filepath)

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip(),
        })

    return {
        "text": result.get("text", "").strip(),
        "segments": segments,
        "language": result.get("language", "unknown"),
        "model": model_name,
    }


def main():
    parser = argparse.ArgumentParser(description="ASR transcription adapter")
    parser.add_argument("file", help="Path to media file")
    parser.add_argument("--model", default="base", help="Whisper model name (tiny, base, small, medium, large)")
    parser.add_argument("--output", default="text", choices=["text", "json"], help="Output format")
    args = parser.parse_args()

    if not Path(args.file).is_file():
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    result = transcribe(args.file, args.model)

    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.output == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["text"])
        if result["segments"]:
            print("\n--- Segments ---", file=sys.stderr)
            for seg in result["segments"]:
                print(f"[{seg['start']:.1f}-{seg['end']:.1f}] {seg['text']}", file=sys.stderr)


if __name__ == "__main__":
    main()
