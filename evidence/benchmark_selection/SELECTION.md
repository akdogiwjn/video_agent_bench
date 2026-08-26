# Benchmark Selection Evidence

## Selection criteria

Three upstream benchmarks are used in this project, each with a distinct role:

### VBench (GEN task content source)

- **Repository**: `Vchitect/VBench`
- **Commit**: `fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490`
- **Role**: GEN task content source — provides public prompt suite for video generation tasks
- **Selection rationale**:
  - Public, peer-reviewed benchmark (CVPR 2024 Highlight)
  - Provides 800 original + 800 GPT-enhanced longer prompts across 8 categories
  - Prompts describe content only, not tool call sequences — preserves agent autonomy
  - Includes VBench-Long evaluation dimensions for long-form video quality
- **Frozen files**: `prompts/` directory (38 files, 1600 prompts)
- **Usage**: GEN case `gen_case_001` uses prompt `gpt_enhanced_longer_scenery_045`

### VideoWeaver (GEN agentic execution + skills + evaluation basis)

- **Repository**: `JianhuiWei7/VideoWeaver`
- **Commit**: `c809392fe6c2c8b22472049684aaefc650e31bde`
- **Role**: GEN agentic execution pattern, foundation skills, process/output evaluation methodology
- **Selection rationale**:
  - Provides foundation skills (image-gen, video-gen, merge-video, ASR, frame extraction, output-eval, etc.)
  - Built on OpenClaw pipeline (same agent framework as this project)
  - Provides PRM (process) and ORM (output) evaluators
  - Agent autonomy: composition skills are generated at runtime, not pre-baked
- **Frozen files**: `skills/` directory (81 files)
- **NOT used as**: case source. VideoWeaver Dataset is not publicly released.
- **Dataset scanner**: `selection/inventory_videoweaver.py` is RESERVED/disabled for future use.

### AgenticVBench (EDIT official case source)

- **Repository**: `PhiloLabs/agentic-vbench`
- **Commit**: `4bb09e0478be8008f7baba518c5d8ec3f3fab7a3`
- **Role**: EDIT official case source — 36 Repurpose tasks (long video → short vertical clip)
- **Selection rationale**:
  - 36 real-world post-production tasks authored by industry experts
  - Each task has an independent creative brief (`instruction.md`)
  - Each task has a per-task verifier (`judge.py` + `rubric.json`)
  - Deterministic format checks + rubric-based LLM judge
  - Source materials available on HuggingFace (`ameddserM/agentic_vbench_video_repurpose`)
- **Frozen files**: `tasks_repurpose/` (36 tasks, 396 files) + `docs/VERIFIER_DESIGN.md`
- **Note**: Harbor is NOT used. Materials are downloaded and frozen into our own `cases/edit/` directory.

### MLPerf / MLCommons (methodology reference)

- **Repository**: `mlcommons/inference`
- **Role**: Methodology reference — case standardization, freeze, reproducibility, sample subset selection
- **Usage**: Referenced for benchmark freeze/reproducibility methodology. Not used as a direct case source.
- If a prompt from the MLPerf 248 accuracy samples subset is used, it is recorded as both VBench-sourced and MLPerf subset.
