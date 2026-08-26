# video_agent_bench — Agent Instructions

## Quick reference commands

```bash
# Verify all milestones
python3 tools/verify_milestone1.py
python3 tools/verify_milestone3.py
python3 tools/verify_milestone4.py
python3 tools/verify_milestones_5_8.py

# Run inventory
python3 selection/inventory_videoweaver.py --dataset-root <path>
python3 selection/inventory_agentic_vbench.py --tasks-root upstream/agentic_vbench/tasks_repurpose

# Run case selection
python3 selection/select_gen_case.py
python3 selection/select_edit_case.py

# Run a case (dry run)
python3 runner/run_case.py --case edit --dry-run --skip-verify

# Run a case (real)
python3 runner/run_case.py --case edit --model anthropic/claude-sonnet-4-6 --timeout 3600

# Verify results
python3 verifier/verify_provenance.py --results results/<run-id>
python3 verifier/verify_execution.py --results results/<run-id>
python3 verifier/edit/evaluate.py --results results/<run-id> --task-id football
```

## Constraints

- No re-writing of official benchmark instructions.
- No self-generated GEN/EDIT fixtures replacing official materials.
- Runner only manages infrastructure; never completes business tasks.
- Verifier runs after the agent stops, in an isolated process.
- Complete original trajectory is always preserved.
- Any deviation from upstream is recorded in a manifest.

## Blocked items

- **GEN**: VideoWeaver dataset not yet released. Infrastructure is ready.
- **EDIT source.mp4**: Needs download from HuggingFace (network not available during setup).
- **Docker image**: Needs build with network access (apt-get, pip, OpenClaw installer).
