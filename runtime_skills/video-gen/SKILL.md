# video-gen (adapted)

Generates videos from text prompts using DashScope Wan Video API.

This is an adapted version of the VideoWeaver video-gen skill.
The original skill uses Volcengine ARK/Seedance; this version uses
DashScope Wan Video as the generation backend.

The skill design (input/output semantics, OUTPUT_DIR mechanism) is
preserved from VideoWeaver. Only the provider backend is changed.

## Usage

```bash
python scripts/generate.py --prompt "A sunset over the ocean" --output video.mp4
```

## Environment

- `DASHSCOPE_API_KEY` — required
- `VIDEO_GEN_MODEL` — required (e.g. wan-style-anime-v1.0)
- `OUTPUT_DIR` — optional (output directory fallback)

## Adaptation

- Original: VideoWeaver skills/video-gen (Volcengine ARK / Seedance)
- Adapted: DashScope Wan Video
- Skill name, input/output semantics: unchanged
