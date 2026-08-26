# Benchmark Selection Evidence

## Selection criteria

Two upstream benchmarks were selected for this project:

### VideoWeaver (GEN)

- **Repository**: `JianhuiWei7/VideoWeaver`
- **Commit**: `c809392fe6c2c8b22472049684aaefc650e31bde`
- **Role**: GEN workload — long video generation via foundation skills + OpenClaw
- **Selection rationale**:
  - Provides foundation skills (image-gen, video-gen, merge-video, ASR, frame extraction, output-eval, etc.)
  - Built on OpenClaw pipeline (same agent framework as this project)
  - Provides PRM (process) and ORM (output) evaluators
  - Agent autonomy: composition skills are generated at runtime, not pre-baked
- **Frozen files**: `skills/` directory (81 files)
- **Known limitation**: Dataset directory is not yet publicly released (placeholder README). Case selection for GEN is blocked until the dataset becomes available.

### AgenticVBench (EDIT)

- **Repository**: `PhiloLabs/agentic-vbench`
- **Commit**: `4bb09e0478be8008f7baba518c5d8ec3f3fab7a3`
- **Role**: EDIT workload — 36 Repurpose tasks (long video → short vertical clip)
- **Selection rationale**:
  - 36 real-world post-production tasks authored by industry experts
  - Each task has an independent creative brief (`instruction.md`)
  - Each task has a per-task verifier (`judge.py` + `rubric.json`)
  - Deterministic format checks + rubric-based LLM judge
  - Source materials available on HuggingFace (`ameddserM/agentic_vbench_video_repurpose`)
- **Frozen files**: `tasks_repurpose/` (36 tasks, 396 files) + `docs/VERIFIER_DESIGN.md`
- **Note**: Harbor is NOT used. Materials are downloaded and frozen into our own `cases/edit/` directory.
