# image-gen (adapted)

Generates images from text prompts using DashScope Wan Image API.

This is an adapted version of the VideoWeaver image-gen skill.
The original skill uses Volcengine ARK/Seedream; this version uses
DashScope Wan Image as the generation backend.

The skill design (input/output semantics, OUTPUT_DIR mechanism) is
preserved from VideoWeaver. Only the provider backend is changed.

## Usage

```bash
python scripts/generate.py --prompt "A sunset over the ocean" --output image.png
```

## Environment

- `DASHSCOPE_API_KEY` — required
- `IMAGE_GEN_MODEL` — required (e.g. wan-style-anime-v1.0)
- `OUTPUT_DIR` — output directory (from get-output-dir skill)

## Adaptation

- Original: VideoWeaver skills/image-gen (Volcengine ARK / Seedream)
- Adapted: DashScope Wan Image
- Skill name, input/output semantics: unchanged
