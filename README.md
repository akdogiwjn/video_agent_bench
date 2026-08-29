# video_agent_bench

Two video-agent benchmark workloads running under a unified Docker image and
OpenClaw, evaluated by benchmark-derived verification.

```
GEN:
VBench / VBench-Long Prompt
          +
VideoWeaver Agentic Pattern
          ↓
Multi-Benchmark-derived Case
          ↓
OpenClaw
          ↓
VideoWeaver Skills + Generic Media Tools
          ↓
Trace + Intermediate Artifacts
          ↓
final.mp4
          ↓
Benchmark-derived Evaluation

EDIT:
AgenticVBench Repurpose Official Task
          ↓
OpenClaw
          ↓
Generic Media Tools
          ↓
Trace + Intermediate Artifacts
          ↓
repurpose.mp4
          ↓
AgenticVBench Verification
```

## Provider Mapping

This project uses DeepSeek + DashScope as the default provider backend.
VideoWeaver frozen skills are adapted to use DashScope instead of Volcengine ARK.

| Capability | Provider | Model | Env Var |
|-----------|----------|-------|---------|
| Agent LLM | DeepSeek | deepseek-v4-flash | `DEEPSEEK_API_KEY` |
| VLM (visual understanding / semantic judge) | DashScope | qwen-vl-max | `DASHSCOPE_API_KEY` + `VLM_MODEL` |
| Omni (audio/video understanding) | DashScope | configurable | `OMNI_MODEL` |
| Image generation (adapted from VideoWeaver image-gen) | DashScope Wan | configurable | `IMAGE_GEN_MODEL` |
| Video generation (adapted from VideoWeaver video-gen) | DashScope Wan | configurable | `VIDEO_GEN_MODEL` |
| ASR | local Whisper | base | (no key needed) |
| Media editing | FFmpeg / Python | — | — |

**VideoWeaver**: foundation skill / agentic pattern source. Generation backend
adapted to DashScope Wan. Original skills remain frozen in `upstream/`.

**AgenticVBench**: official task/rubric source. Default local configuration uses
adapted Qwen-VL/Qwen-Omni verifier (`EDIT_VERIFIER_MODE=adapted`). Official
Gemini + Anthropic verifier remains available (`EDIT_VERIFIER_MODE=official`).
Adapted verifier output is NOT official AgenticVBench score.

## Upstream benchmarks

| Benchmark | Repository | Commit | Role in project |
|-----------|-----------|--------|------|
| VBench | `Vchitect/VBench` | see `upstream/vbench/COMMIT` | GEN task content source (public prompt suite) |
| VideoWeaver | `JianhuiWei7/VideoWeaver` | see `upstream/videoweaver/COMMIT` | GEN agentic execution pattern, foundation skills, process/output evaluation methodology |
| AgenticVBench | `PhiloLabs/agentic-vbench` | see `upstream/agentic_vbench/COMMIT` | EDIT official case source (36 Repurpose tasks) |

## GEN workload

GEN cases are **multi-benchmark-derived**, not official VideoWeaver cases:

- **Task content**: from VBench public prompt suite (GPT-enhanced longer prompts)
- **Agentic execution pattern**: from VideoWeaver (OpenClaw pipeline, composition skills)
- **Foundation skills**: from VideoWeaver (image-gen, video-gen, merge-video, etc.)
- **Evaluation methodology**: VideoWeaver process/output evaluation + VBench quality dimensions
- **Methodology reference**: MLPerf/MLCommons (case standardization, freeze, reproducibility)

VideoWeaver Dataset is NOT used as a case source in this project. The dataset
is not yet publicly released. VideoWeaver is used as agentic execution / skills /
evaluation basis only.

## EDIT workload

EDIT uses AgenticVBench Repurpose official task, with controlled adaptation:

- **Official task**: AgenticVBench football instruction.md (unmodified)
- **Official rubric**: football rubric.json + judge.py (frozen in upstream/)
- **Adapted source material**: football_short — 14min compact extract of the
  official 3h20min source.mp4, preserving all rubric-referenced segments
- **case_source**: adapted (football_short) / official (football)
- **upstream_task_id**: football (rubric source)
- **Verifier**: adapted mode uses Qwen-VL (visual judge) + Qwen-Omni (audio
  judge) + Whisper (transcript comparison). Official mode (Gemini + Anthropic)
  remains available via `EDIT_VERIFIER_MODE=official`.

Two EDIT case variants:

| Case | Source | Duration | case_source | Purpose |
|------|--------|----------|-------------|---------|
| `football` | official 2.47GB | 12011s | official | Final benchmark verification |
| `football_short` | adapted 307MB extract | 842s | adapted | Development, perf testing |

## Milestones

1. **Upstream freeze** — clone, record commit, copy foundation skills / tasks /
   prompts, compute SHA256, generate `source_manifest.json`, write inventory scripts.
2. **Case selection** — VBench-based rule-based selection for GEN; AgenticVBench
   rule-based selection for EDIT.
3. **Case import** — `cases/gen/gen_case_001/` and `cases/edit/` with
   `benchmark_source.json`, `adaptation.json`, and SHA256 manifests.
4. **Unified Docker image** — `video-agent-bench:1.0` (no case baked in).
5. **OpenClaw runner** — `run_case.py`, `entrypoint.sh`, workspace mount,
   trajectory collection.
6. **GEN** — VBench-derived case + VideoWeaver foundation skills + OpenClaw.
7. **EDIT** — AgenticVBench Repurpose + OpenClaw + generic media environment.
8. **Native verification** — project-defined deterministic rubric (GEN) +
   AgenticVBench verifier (EDIT).

## Constraints

- Original benchmark prompts are preserved verbatim; all adaptations are documented.
- Instruction describes what to produce, not how (no hardcoded tool call sequences).
- Runner only manages infrastructure; it never completes business tasks.
- Verifier runs after the agent stops, in an isolated process.
- Complete original trajectory is always preserved.
- Any deviation from upstream is recorded in adaptation.json / manifests.
- EDIT official task semantics are never modified.
