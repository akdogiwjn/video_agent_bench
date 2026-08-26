# video_agent_bench

Two real, upstream-frozen video-agent benchmark workloads running under a
unified Docker image and OpenClaw, evaluated by each benchmark's own verifier.

```
VideoWeaver / AgenticVBench
           ↓
      frozen commit
           ↓
      official case
           ↓
   original task / input
           ↓
  unified Docker image
           ↓
        OpenClaw
           ↓
 Benchmark-derived tools
           ↓
 original trajectory
           ↓
intermediate artifacts
           ↓
       final video
           ↓
 independent benchmark verifier
```

## Upstream benchmarks

| Benchmark | Repository | Commit | Role |
|-----------|-----------|--------|------|
| VideoWeaver | `JianhuiWei7/VideoWeaver` | see `upstream/videoweaver/COMMIT` | GEN workload: foundation skills + long video generation |
| AgenticVBench | `PhiloLabs/agentic-vbench` | see `upstream/agentic_vbench/COMMIT` | EDIT workload: 36 Repurpose tasks (long video → short vertical) |

## Milestones

1. **Upstream freeze** — clone, record commit, copy foundation skills / tasks,
   compute SHA256, generate `source_manifest.json`, write inventory scripts.
2. **Case selection** — explicit rule-based selection from inventory output.
3. **Case import** — `cases/gen/` and `cases/edit/` with `benchmark_source.json`
   and SHA256 manifests.
4. **Unified Docker image** — `video-agent-bench:1.0` (no case baked in).
5. **OpenClaw runner** — `run_case.py`, `entrypoint.sh`, workspace mount,
   trajectory collection.
6. **GEN** — VideoWeaver case + foundation skills + OpenClaw.
7. **EDIT** — AgenticVBench Repurpose + OpenClaw + generic media environment.
8. **Native verification** — VideoWeaver PRM/ORM + AgenticVBench verifier.

## Constraints

- No re-writing of official benchmark instructions.
- No self-generated GEN/EDIT fixtures replacing official materials.
- Runner only manages infrastructure; it never completes business tasks.
- Verifier runs after the agent stops, in an isolated process.
- Complete original trajectory is always preserved.
- Any deviation from upstream is recorded in a manifest.
