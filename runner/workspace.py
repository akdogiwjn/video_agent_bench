"""Workspace management for video_agent_bench runner.

Creates and populates the unified /workspace/ layout inside a Docker container
or local directory. Cases are injected via mount — the image never contains
case data.

Layout (identical for GEN and EDIT; unused dirs stay empty):

    /workspace/
    ├── task/          # instruction.md + brief.md
    ├── materials/     # source.mp4 (EDIT) or empty (GEN)
    ├── references/    # reference images/videos/audio (GEN) or empty (EDIT)
    ├── skills/        # foundation skills (GEN) or empty (EDIT)
    ├── output/        # final artifact (repurpose.mp4 / final.mp4)
    └── logs/          # agent stdout, stderr, trajectory
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


WORKSPACE_DIRS = ["task", "materials", "references", "skills", "output", "logs", "tools"]

# Skills that are implicitly required by other skills.
# Discovered by scanning VideoWeaver skill source code for cross-references
# like: os.path.join(os.path.dirname(__file__), "../../get-output-dir/...")
SKILL_DEPENDENCIES = {
    "image-gen": ["get-output-dir"],
    "video-gen": ["get-output-dir"],
    "extract-video-frame": ["get-output-dir"],
    "merge-video": ["get-output-dir"],
    "trim-video": [],
    "trim-audio": ["get-output-dir"],
    "change-fps": ["get-output-dir"],
    "resize-video-resolution": ["get-output-dir"],
    "resize-image-resolution": ["get-output-dir"],
    "grid-generate": ["get-output-dir"],
    "add-audio-track": [],
    "replace-audio": [],
    "split-audio": [],
    "split-image": [],
    "video-shot-split": [],
    "get-video-metadata": [],
    "get-image-metadata": [],
    "get-output-dir": [],
    "task-tracker": ["get-output-dir"],
    "vision-understanding": [],
    "text-to-speech": [],
    "audio-gen": [],
    "audio-understanding": [],
    "audio-vocal-separate": [],
    "automatic-speech-recognition": [],
    "process-eval": [],
    "output-eval": [],
    "skill-creator": [],
    "video-skill-creator": [],
    "skill-optimizer": [],
    "pair-wise-skill-merge": [],
}


def resolve_skill_dependencies(visible_capabilities: list[str]) -> list[str]:
    """Compute the transitive closure of skill dependencies.

    Given a list of visible capabilities, expand it to include all
    skills that those capabilities implicitly depend on (e.g.,
    image-gen depends on get-output-dir).
    """
    resolved = set()
    queue = list(visible_capabilities)
    while queue:
        cap = queue.pop(0)
        if cap in resolved:
            continue
        resolved.add(cap)
        deps = SKILL_DEPENDENCIES.get(cap, [])
        for dep in deps:
            if dep not in resolved:
                queue.append(dep)
    return sorted(resolved)


def create_workspace(root: Path) -> Path:
    """Create the unified workspace directory structure under `root`."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for d in WORKSPACE_DIRS:
        (root / d).mkdir(exist_ok=True)

    # Copy thin capability adapters (VLM, ASR, inspect_media, extract_frames)
    # into workspace/tools/ so the agent can use them.
    tools_src = Path(__file__).resolve().parent.parent / "tools" / "media"
    tools_dst = root / "tools"
    if tools_src.is_dir():
        for f in tools_src.iterdir():
            if f.is_file() and f.suffix == ".py" and f.name != "__init__.py":
                shutil.copy2(f, tools_dst / f.name)

    # Copy DashScope provider adapters into workspace/tools/providers/
    providers_src = Path(__file__).resolve().parent.parent / "tools" / "providers"
    providers_dst = tools_dst / "providers"
    if providers_src.is_dir():
        providers_dst.mkdir(exist_ok=True)
        (providers_dst / "__init__.py").touch()
        for f in providers_src.iterdir():
            if f.is_file() and f.suffix == ".py" and f.name != "__init__.py":
                shutil.copy2(f, providers_dst / f.name)

    return root


def populate_task(workspace: Path, case_dir: Path) -> list[Path]:
    """Copy task files (instruction.md, brief.md, etc.) into workspace/task/."""
    task_src = case_dir / "task"
    task_dst = workspace / "task"
    copied = []
    if task_src.is_dir():
        for f in sorted(task_src.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                shutil.copy2(f, task_dst / f.name)
                copied.append(task_dst / f.name)
    return copied


def populate_materials(workspace: Path, case_dir: Path) -> list[Path]:
    """Copy source materials into workspace/materials/."""
    mat_src = case_dir / "materials"
    mat_dst = workspace / "materials"
    copied = []
    if mat_src.is_dir():
        for f in sorted(mat_src.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                shutil.copy2(f, mat_dst / f.name)
                copied.append(mat_dst / f.name)
    return copied


def populate_references(workspace: Path, case_dir: Path) -> list[Path]:
    """Copy reference files into workspace/references/."""
    ref_src = case_dir / "references"
    ref_dst = workspace / "references"
    copied = []
    if ref_src.is_dir():
        for f in sorted(ref_src.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                shutil.copy2(f, ref_dst / f.name)
                copied.append(ref_dst / f.name)
    return copied


def populate_skills(workspace: Path, skills_root: Path, visible_capabilities: list[str]) -> list[Path]:
    """Copy foundation skills into workspace/skills/ based on visible_capabilities.

    For GEN cases:
    - image-gen and video-gen use ADAPTED skills (runtime_skills/) with DashScope backend
    - Other skills (merge-video, extract-video-frame, get-output-dir, etc.) use
      the original frozen VideoWeaver skills (upstream/videoweaver/skills/)
    - Dependency closure is resolved automatically

    For EDIT cases, skills/ stays empty (the agent uses shell/python/ffmpeg directly).
    """
    skills_dst = workspace / "skills"
    copied = []
    if not skills_root.is_dir():
        return copied

    # Adapted skills that use DashScope instead of Volcengine ARK
    adapted_skill_names = {"image-gen", "video-gen"}
    adapted_skills_root = ROOT / "runtime_skills"

    # Map capability names to skill directory names
    capability_to_skill = {
        "image-gen": "image-gen",
        "video-gen": "video-gen",
        "merge-video": "merge-video",
        "extract-video-frame": "extract-video-frame",
        "automatic-speech-recognition": "automatic-speech-recognition",
        "audio-gen": "audio-gen",
        "audio-understanding": "audio-understanding",
        "add-audio-track": "add-audio-track",
        "replace-audio": "replace-audio",
        "trim-video": "trim-video",
        "trim-audio": "trim-audio",
        "change-fps": "change-fps",
        "resize-video-resolution": "resize-video-resolution",
        "resize-image-resolution": "resize-image-resolution",
        "split-image": "split-image",
        "split-audio": "split-audio",
        "video-shot-split": "video-shot-split",
        "grid-generate": "grid-generate",
        "get-video-metadata": "get-video-metadata",
        "get-image-metadata": "get-image-metadata",
        "get-output-dir": "get-output-dir",
        "task-tracker": "task-tracker",
        "vision-understanding": "vision-understanding",
        "text-to-speech": "text-to-speech",
        "process-eval": "process-eval",
        "output-eval": "output-eval",
        "skill-creator": "skill-creator",
        "video-skill-creator": "video-skill-creator",
        "skill-optimizer": "skill-optimizer",
        "pair-wise-skill-merge": "pair-wise-skill-merge",
        "audio-vocal-separate": "audio-vocal-separate",
    }

    # Resolve transitive dependencies (e.g., image-gen → get-output-dir)
    resolved_caps = resolve_skill_dependencies(visible_capabilities)

    for cap in resolved_caps:
        skill_name = capability_to_skill.get(cap)
        if skill_name is None:
            continue
        # Use adapted skills for image-gen/video-gen (DashScope backend)
        # Use original frozen VideoWeaver skills for everything else
        if skill_name in adapted_skill_names and (adapted_skills_root / skill_name).is_dir():
            skill_src = adapted_skills_root / skill_name
        else:
            skill_src = skills_root / skill_name
        if skill_src.is_dir():
            skill_dst_dir = skills_dst / skill_name
            if not skill_dst_dir.exists():
                shutil.copytree(skill_src, skill_dst_dir, dirs_exist_ok=True)
                copied.append(skill_dst_dir)

    return copied


def cleanup_workspace(workspace: Path):
    """Remove the workspace directory (used after run is complete)."""
    workspace = Path(workspace)
    if workspace.exists():
        shutil.rmtree(workspace)
