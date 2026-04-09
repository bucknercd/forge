"""
User-facing workflow labels derived from file-backed prompt-task and task files.

Does not introduce a separate source of truth; only summarizes existing state.
"""

from __future__ import annotations

from forge.design_manager import MilestoneService
from forge.prompt_task_state import (
    TASK_STATUS_ACTIVE,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_PENDING,
    PromptTask,
    load_prompt_task_state,
)
from forge.task_service import list_tasks, task_count_for_milestone


def prompt_tasks_for_milestone(milestone_id: int) -> list[PromptTask]:
    return [t for t in load_prompt_task_state().tasks if t.milestone_id == milestone_id]


def infer_milestone_workflow_label(milestone_id: int) -> str:
    """
    completed — all known prompt tasks for this milestone are completed.
    in_progress — at least one active, or mix of completed and non-completed.
    pending — synced prompt tasks exist and all are pending (none active/completed).
    not_synced — milestone has expanded tasks on disk but no prompt tasks for it.
    no_tasks — no rows under .system/tasks for this milestone.
    """
    n_tasks = task_count_for_milestone(milestone_id)
    if n_tasks == 0:
        return "no_tasks"
    synced = prompt_tasks_for_milestone(milestone_id)
    if not synced:
        return "not_synced"
    statuses = [t.status for t in synced]
    if all(s == TASK_STATUS_COMPLETED for s in statuses):
        return "completed"
    if any(s == TASK_STATUS_ACTIVE for s in statuses):
        return "in_progress"
    if any(s == TASK_STATUS_COMPLETED for s in statuses):
        return "in_progress"
    if all(s == TASK_STATUS_PENDING for s in statuses):
        return "pending"
    return "in_progress"


def _display_label(raw: str) -> str:
    return {
        "completed": "completed",
        "in_progress": "active / in progress",
        "pending": "pending",
        "not_synced": "pending (not synced — run prompt-task-sync)",
        "no_tasks": "no tasks expanded",
    }.get(raw, raw)


def format_milestone_workflow_display(milestone_id: int) -> str:
    return _display_label(infer_milestone_workflow_label(milestone_id))


def current_focus_milestone_id() -> int | None:
    """
    Prefer the milestone of the active prompt task; else the first milestone that is
    not workflow-completed; else None if no milestones.
    """
    st = load_prompt_task_state()
    if st.active_task_id is not None:
        row = next((t for t in st.tasks if t.id == st.active_task_id), None)
        if row is not None and row.milestone_id is not None:
            return int(row.milestone_id)
    try:
        milestones = MilestoneService.list_milestones()
    except ValueError:
        return None
    for m in milestones:
        if infer_milestone_workflow_label(m.id) != "completed":
            return m.id
    return milestones[-1].id if milestones else None


def prompt_task_by_milestone_task(milestone_id: int, milestone_task_id: int) -> PromptTask | None:
    for t in load_prompt_task_state().tasks:
        if t.milestone_id == milestone_id and t.task_id == milestone_task_id:
            return t
    return None


def recommend_next_command(*, focus_mid: int | None) -> str | None:
    if focus_mid is None:
        return "Run `forge init` or open docs/milestones.md to add milestones."
    label = infer_milestone_workflow_label(focus_mid)
    if label == "no_tasks":
        return f"Run `forge task-expand --milestone {focus_mid}`."
    if label == "not_synced":
        return f"Run `forge prompt-task-sync --milestone {focus_mid}`."
    st = load_prompt_task_state()
    if st.active_task_id is None:
        pending = [t for t in st.tasks if t.milestone_id == focus_mid and t.status == TASK_STATUS_PENDING]
        if pending:
            return (
                f"Run `forge prompt-task-start --id {pending[0].id}` to set an active task, "
                "then `forge prompt-generate --milestone <m> --task <t>`."
            )
        return f"Run `forge milestone-list` — milestone {focus_mid} may be finished or needs more tasks."
    row = next((t for t in st.tasks if t.id == st.active_task_id), None)
    if row is None or row.task_id is None or row.milestone_id is None:
        return "Run `forge prompt-generate --milestone <m> --task <t>` when ready to implement."
    return (
        f"Implement the active task, then `forge task-complete` (or "
        f"`forge prompt-generate --milestone {row.milestone_id} --task {row.task_id}` first)."
    )
