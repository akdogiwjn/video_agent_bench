# video_agent_bench — Agent Instructions

## Quick reference commands

```bash
# Verify all milestones
python3 tools/verify_milestone1.py
python3 tools/verify_milestone3.py
python3 tools/verify_milestone4.py
python3 tools/verify_milestones_5_8.py

# Run VBench inventory (GEN prompt candidates)
python3 case_design/inventory_vbench.py --prompts-root upstream/vbench/prompts

# Run AgenticVBench inventory (EDIT task candidates)
python3 selection/inventory_agentic_vbench.py --tasks-root upstream/agentic_vbench/tasks_repurpose

# Run case selection
python3 selection/select_gen_case.py
python3 selection/select_edit_case.py

# Run a case (dry run)
python3 runner/run_case.py --case edit --dry-run --skip-verify
python3 runner/run_case.py --case gen --dry-run

# Run a case (real)
python3 runner/run_case.py --case edit --model anthropic/claude-sonnet-4-6 --timeout 3600
python3 runner/run_case.py --case gen --model anthropic/claude-sonnet-4-6 --timeout 3600

# Verify results
python3 verifier/verify_provenance.py --results results/<run-id>
python3 verifier/verify_execution.py --results results/<run-id>
python3 verifier/edit/evaluate.py --results results/<run-id> --task-id football
python3 verifier/gen/evaluate.py --results results/<run-id>
```

## Case sources

### GEN: multi-benchmark-derived
- Task content: VBench public prompt suite (frozen at `upstream/vbench/`)
- Agentic execution + skills + evaluation: VideoWeaver (frozen at `upstream/videoweaver/`)
- Methodology reference: MLPerf/MLCommons
- case_source = "multi-benchmark-derived", official_benchmark_case = false
- Original VBench prompt preserved in `cases/gen/gen_case_001/source/original_prompt.txt`
- All adaptations documented in `cases/gen/gen_case_001/adaptation.json`

### EDIT: official
- AgenticVBench Repurpose official task (frozen at `upstream/agentic_vbench/`)
- case_source = "official", official_benchmark_case = true
- Instruction, materials, and verifier are official and unmodified

## Constraints

- Original benchmark prompts are preserved verbatim; all adaptations are documented.
- Instruction describes what to produce, not how (no hardcoded tool call sequences).
- Runner only manages infrastructure; never completes business tasks.
- Verifier runs after the agent stops, in an isolated process.
- Complete original trajectory is always preserved.
- Any deviation from upstream is recorded in adaptation.json / manifests.
- EDIT official task semantics are never modified.

## Blocked items

- **EDIT source.mp4**: Needs download from HuggingFace (network not available during setup).
- **Docker image**: Needs build with network access (apt-get, pip, OpenClaw installer).
