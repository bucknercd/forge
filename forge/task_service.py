"""
Task breakdown storage and bridge to milestone-shaped execution units.

Tasks live under ``.system/tasks/m<milestone_id>.json`` (inspectable JSON).
Execution still uses :class:`forge.design_manager.Milestone` shells so
:class:`forge.execution.plan.ExecutionPlanBuilder` and reviewed-plan apply
semantics stay unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge.design_manager import Milestone, MilestoneService
from forge.paths import Paths


def tasks_dir() -> Path:
    d = Paths.SYSTEM_DIR / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tasks_file_for_milestone(milestone_id: int) -> Path:
    return tasks_dir() / f"m{milestone_id}.json"


@dataclass
class Task:
    """Execution-level unit under a parent milestone."""

    id: int
    milestone_id: int
    title: str
    objective: str
    summary: str
    depends_on: list[int] = field(default_factory=list)
    files_allowed: str | None = None
    validation: str = ""
    done_when: str = ""
    status: str = "not_started"
    forge_actions: list[str] = field(default_factory=list)
    forge_validation: list[str] = field(default_factory=list)

    def with_lines_tuples(self) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
        return (
            [(0, a) for a in self.forge_actions],
            [(0, v) for v in self.forge_validation],
        )


def task_to_execution_milestone(parent: Milestone, task: Task) -> Milestone:
    """
    Build a :class:`Milestone` shaped object for planners/appliers.

    Uses the parent milestone id so ``mark_milestone_completed`` still targets
    the roadmap milestone in ``docs/milestones.md``.
    """
    awl, vwl = task.with_lines_tuples()
    return Milestone(
        id=parent.id,
        title=f"{parent.title} :: {task.title}",
        objective=task.objective,
        scope=task.summary or task.objective or parent.scope,
        validation=task.validation or parent.validation,
        summary=parent.summary,
        depends_on=list(parent.depends_on),
        forge_actions=list(task.forge_actions),
        forge_validation=list(task.forge_validation),
        forge_actions_with_lines=awl,
        forge_validation_with_lines=vwl,
    )


def _task_from_dict(milestone_id: int, data: dict[str, Any]) -> Task:
    return Task(
        id=int(data["id"]),
        milestone_id=milestone_id,
        title=str(data.get("title", "")),
        objective=str(data.get("objective", "")),
        summary=str(data.get("summary", "")),
        depends_on=[int(x) for x in data.get("depends_on", [])],
        files_allowed=data.get("files_allowed"),
        validation=str(data.get("validation", "")),
        done_when=str(data.get("done_when", "")),
        status=str(data.get("status", "not_started")),
        forge_actions=[str(x) for x in data.get("forge_actions", [])],
        forge_validation=[str(x) for x in data.get("forge_validation", [])],
    )


def list_tasks(milestone_id: int) -> list[Task]:
    path = tasks_file_for_milestone(milestone_id)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks_raw = data.get("tasks", [])
    return [_task_from_dict(milestone_id, t) for t in tasks_raw]


def get_task(milestone_id: int, task_id: int) -> Task | None:
    for t in list_tasks(milestone_id):
        if t.id == task_id:
            return t
    return None


def task_count_for_milestone(milestone_id: int) -> int:
    return len(list_tasks(milestone_id))


def save_tasks(milestone_id: int, tasks: list[Task]) -> None:
    path = tasks_file_for_milestone(milestone_id)
    tasks_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "milestone_id": milestone_id,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "objective": t.objective,
                "summary": t.summary,
                "depends_on": t.depends_on,
                "files_allowed": t.files_allowed,
                "validation": t.validation,
                "done_when": t.done_when,
                "status": t.status,
                "forge_actions": t.forge_actions,
                "forge_validation": t.forge_validation,
            }
            for t in tasks
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def expand_milestone_to_tasks(*, milestone_id: int, force: bool = False) -> dict[str, Any]:
    """
    Ensure milestone ``milestone_id`` has a task breakdown.

    Default behavior creates a **single compatibility task** that copies the
    milestone's Forge Actions / Forge Validation so existing repos behave like
    milestone-centric planning until you add more tasks in the JSON file.
    """
    parent = MilestoneService.get_milestone(milestone_id)
    if not parent:
        return {"ok": False, "message": f"Unknown milestone id {milestone_id}."}
    path = tasks_file_for_milestone(milestone_id)
    if path.exists() and not force:
        existing = list_tasks(milestone_id)
        if existing:
            return {
                "ok": True,
                "message": (
                    f"Tasks already exist for milestone {milestone_id} "
                    f"({len(existing)} task(s)). Use --force to replace from the "
                    "current milestone definition."
                ),
                "task_count": len(existing),
                "skipped": True,
            }

    title_line = parent.title
    if ":" in title_line:
        short_title = title_line.split(":", 1)[-1].strip()
    else:
        short_title = title_line.strip()
    compat = Task(
        id=1,
        milestone_id=milestone_id,
        title=short_title or f"Milestone {milestone_id} work",
        objective=parent.objective,
        summary=parent.summary or parent.scope,
        depends_on=[],
        files_allowed=None,
        validation=parent.validation,
        done_when=parent.validation,
        status="not_started",
        forge_actions=list(parent.forge_actions),
        forge_validation=list(parent.forge_validation),
    )
    save_tasks(milestone_id, [compat])
    try:
        rel = path.relative_to(Paths.BASE_DIR).as_posix()
    except ValueError:
        rel = str(path)
    return {
        "ok": True,
        "message": (
            f"Expanded milestone {milestone_id} into 1 compatibility task "
            f"(mirrors Forge Actions / Validation). Edit `{rel}` to split work."
        ),
        "task_count": 1,
        "skipped": False,
        "tasks_path": str(path),
    }
