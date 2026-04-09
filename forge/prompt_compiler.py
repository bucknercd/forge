"""
Task-scoped prompt compiler for prompt-driven workflow.
"""

from __future__ import annotations

from pathlib import Path

from forge.design_manager import MilestoneService
from forge.paths import Paths
from forge.task_service import get_task


def prompts_dir() -> Path:
    d = Paths.SYSTEM_DIR / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prompt_artifact_path(milestone_id: int, task_id: int) -> Path:
    return prompts_dir() / f"m{milestone_id}-t{task_id}.prompt.txt"


def compile_task_prompt(milestone_id: int, task_id: int) -> str:
    milestone = MilestoneService.get_milestone(milestone_id)
    if milestone is None:
        raise ValueError(f"Unknown milestone id {milestone_id}.")
    task = get_task(milestone_id, task_id)
    if task is None:
        raise ValueError(f"No task {task_id} for milestone {milestone_id}.")

    depends_on = ", ".join(str(d) for d in task.depends_on) if task.depends_on else "None"

    sections: list[str] = [
        "You are implementing one Forge task in a spec-driven workflow.",
        "",
        "## Read First",
        "From this repository, read before editing:",
        "- docs/vision.txt",
        "- docs/requirements.md",
        "- docs/architecture.md",
        "",
        "## Milestone Context",
        f"- Milestone ID: {milestone_id}",
        f"- Milestone title: {milestone.title}",
        f"- Milestone objective: {milestone.objective}",
        f"- Milestone scope: {milestone.scope}",
        f"- Milestone validation: {milestone.validation}",
        "",
        "## Selected Task",
        f"- Task ID: {task_id}",
        f"- Task title: {task.title}",
        f"- Task objective: {task.objective}",
        f"- Task summary: {task.summary}",
        f"- Depends on: {depends_on}",
        f"- Status in task file: {task.status}",
    ]
    if (task.validation or "").strip():
        sections.append(f"- Validation criteria: {task.validation}")
    if (task.done_when or "").strip():
        sections.append(f"- Done criteria: {task.done_when}")

    if (task.files_allowed or "").strip():
        sections.extend(
            [
                "",
                "## Preferred Files",
                "Suggested places to inspect or edit first (guidance only; not exhaustive or exclusive):",
                f"- {task.files_allowed.strip()}",
            ]
        )

    sections.extend(
        [
            "",
            "## Implementation Constraints",
            "- Solve only the task described above.",
            "- Keep the blast radius small.",
            "- Prefer editing existing files over adding new ones.",
            "- Do not introduce new abstractions unless required by this task.",
            "- Do not refactor unrelated code or do incidental cleanup outside this task.",
            "- Do not redesign the architecture.",
            "- Avoid speculative future-proofing.",
            "- Preserve existing naming and structure unless this task explicitly requires otherwise.",
            "- Add only the minimum tests needed for the changed behavior.",
            "- Stop once the task requirements are satisfied.",
            "",
            "## Forge Workflow",
            "- Do not mutate Forge workflow state files directly.",
            "- Forge remains the source of truth for workflow state transitions.",
            "- Task completion is explicit in Forge; do not assume completion.",
            "",
            "## Return",
            "Return a concise summary of changes, tests run, and any assumptions.",
            "",
        ]
    )
    return "\n".join(sections)


def generate_prompt_artifact(milestone_id: int, task_id: int) -> dict[str, str]:
    prompt_text = compile_task_prompt(milestone_id, task_id)
    out_path = prompt_artifact_path(milestone_id, task_id)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(prompt_text, encoding="utf-8")
    tmp.replace(out_path)
    return {
        "milestone_id": str(milestone_id),
        "task_id": str(task_id),
        "prompt_path": str(out_path),
        "prompt_text": prompt_text,
    }
