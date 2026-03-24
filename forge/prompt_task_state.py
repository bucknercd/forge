"""
Persistent prompt-task state for prompt-driven workflow.

Phase 1 scope:
- File-based durable storage under .system/
- Exactly one active task at a time
- Explicit activation/completion APIs (no implicit completion side effects)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any

from forge.paths import Paths
from forge.task_service import list_tasks

TASK_STATUS_PENDING = "pending"
TASK_STATUS_ACTIVE = "active"
TASK_STATUS_COMPLETED = "completed"
_ALLOWED_STATUSES = {
    TASK_STATUS_PENDING,
    TASK_STATUS_ACTIVE,
    TASK_STATUS_COMPLETED,
}
_STATE_VERSION = 1


@dataclass
class PromptTask:
    id: int
    title: str
    objective: str
    status: str = TASK_STATUS_PENDING
    milestone_id: int | None = None
    task_id: int | None = None

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PromptTask":
        status = str(raw.get("status", TASK_STATUS_PENDING)).strip().lower()
        if status not in _ALLOWED_STATUSES:
            status = TASK_STATUS_PENDING
        return PromptTask(
            id=int(raw["id"]),
            title=str(raw.get("title", "")),
            objective=str(raw.get("objective", "")),
            status=status,
            milestone_id=(
                int(raw["milestone_id"])
                if raw.get("milestone_id") is not None
                else None
            ),
            task_id=int(raw["task_id"]) if raw.get("task_id") is not None else None,
        )


@dataclass
class PromptTaskState:
    version: int
    active_task_id: int | None
    tasks: list[PromptTask]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "active_task_id": self.active_task_id,
            "tasks": [asdict(t) for t in self.tasks],
        }


def task_state_path() -> Path:
    return Paths.SYSTEM_DIR / "prompt_tasks.json"


def _legacy_todo_state_path() -> Path:
    return Paths.SYSTEM_DIR / "prompt_todos.json"


def default_prompt_task_state() -> PromptTaskState:
    return PromptTaskState(version=_STATE_VERSION, active_task_id=None, tasks=[])


def _normalize_single_active(state: PromptTaskState) -> PromptTaskState:
    active = state.active_task_id
    if active is not None and all(t.id != active for t in state.tasks):
        active = None

    seen_active = False
    normalized: list[PromptTask] = []
    for t in state.tasks:
        st = t.status if t.status in _ALLOWED_STATUSES else TASK_STATUS_PENDING
        if active is not None and t.id == active:
            st = TASK_STATUS_ACTIVE
            seen_active = True
        elif st == TASK_STATUS_ACTIVE:
            st = TASK_STATUS_PENDING
        normalized.append(
            PromptTask(
                id=t.id,
                title=t.title,
                objective=t.objective,
                status=st,
                milestone_id=t.milestone_id,
                task_id=t.task_id,
            )
        )

    if active is not None and not seen_active:
        active = None
    return PromptTaskState(version=_STATE_VERSION, active_task_id=active, tasks=normalized)


def load_prompt_task_state() -> PromptTaskState:
    path = task_state_path()
    if not path.exists() and _legacy_todo_state_path().exists():
        path = _legacy_todo_state_path()
    if not path.exists():
        return default_prompt_task_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        tasks_blob = raw.get("tasks")
        if tasks_blob is None:
            tasks_blob = raw.get("todos", [])
        tasks = [PromptTask.from_dict(t) for t in list(tasks_blob)]
        active_raw = raw.get("active_task_id")
        if active_raw is None:
            active_raw = raw.get("active_todo_id")
        state = PromptTaskState(
            version=int(raw.get("version", _STATE_VERSION)),
            active_task_id=int(active_raw) if active_raw is not None else None,
            tasks=tasks,
        )
    except Exception:
        return default_prompt_task_state()
    return _normalize_single_active(state)


def save_prompt_task_state(state: PromptTaskState) -> None:
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    path = task_state_path()
    normalized = _normalize_single_active(state)
    payload = normalized.to_dict()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    legacy = _legacy_todo_state_path()
    if legacy.exists() and legacy != path:
        try:
            legacy.unlink()
        except OSError:
            pass


def list_prompt_tasks() -> list[PromptTask]:
    return list(load_prompt_task_state().tasks)


def set_active_task(task_id: int) -> PromptTaskState:
    state = load_prompt_task_state()
    found = False
    out: list[PromptTask] = []
    for t in state.tasks:
        if t.id == task_id:
            if t.status == TASK_STATUS_COMPLETED:
                raise ValueError(f"Task {task_id} is already completed.")
            out.append(
                PromptTask(
                    id=t.id,
                    title=t.title,
                    objective=t.objective,
                    status=TASK_STATUS_ACTIVE,
                    milestone_id=t.milestone_id,
                    task_id=t.task_id,
                )
            )
            found = True
        else:
            st = TASK_STATUS_PENDING if t.status == TASK_STATUS_ACTIVE else t.status
            out.append(
                PromptTask(
                    id=t.id,
                    title=t.title,
                    objective=t.objective,
                    status=st,
                    milestone_id=t.milestone_id,
                    task_id=t.task_id,
                )
            )
    if not found:
        raise ValueError(f"Unknown task id {task_id}.")
    new_state = PromptTaskState(version=_STATE_VERSION, active_task_id=task_id, tasks=out)
    save_prompt_task_state(new_state)
    return load_prompt_task_state()


def complete_task(task_id: int) -> PromptTaskState:
    """
    Explicit completion path: task completion only happens via this call/CLI command.
    """
    state = load_prompt_task_state()
    found = False
    out: list[PromptTask] = []
    active = state.active_task_id
    for t in state.tasks:
        if t.id == task_id:
            found = True
            out.append(
                PromptTask(
                    id=t.id,
                    title=t.title,
                    objective=t.objective,
                    status=TASK_STATUS_COMPLETED,
                    milestone_id=t.milestone_id,
                    task_id=t.task_id,
                )
            )
            if active == task_id:
                active = None
        else:
            out.append(t)
    if not found:
        raise ValueError(f"Unknown task id {task_id}.")
    save_prompt_task_state(PromptTaskState(version=_STATE_VERSION, active_task_id=active, tasks=out))
    return load_prompt_task_state()


def bootstrap_tasks_from_milestone(milestone_id: int, *, force: bool = False) -> PromptTaskState:
    """
    Reuse existing task decomposition as the initial prompt-task inventory.
    """
    state = load_prompt_task_state()
    if state.tasks and not force:
        return state
    task_items = list_tasks(milestone_id)
    tasks: list[PromptTask] = []
    for t in task_items:
        status = TASK_STATUS_COMPLETED if t.status == "completed" else TASK_STATUS_PENDING
        tasks.append(
            PromptTask(
                id=t.id,
                title=t.title,
                objective=t.objective,
                status=status,
                milestone_id=milestone_id,
                task_id=t.id,
            )
        )
    active_id = None
    for td in tasks:
        if td.status == TASK_STATUS_PENDING:
            td.status = TASK_STATUS_ACTIVE
            active_id = td.id
            break
    new_state = PromptTaskState(version=_STATE_VERSION, active_task_id=active_id, tasks=tasks)
    save_prompt_task_state(new_state)
    return load_prompt_task_state()


# Legacy aliases (temporary compatibility for pre-task-first internal callers).
PromptTodo = PromptTask
PromptTodoState = PromptTaskState
TODO_STATUS_PENDING = TASK_STATUS_PENDING
TODO_STATUS_ACTIVE = TASK_STATUS_ACTIVE
TODO_STATUS_COMPLETED = TASK_STATUS_COMPLETED
todo_state_path = task_state_path
load_todo_state = load_prompt_task_state
save_todo_state = save_prompt_task_state
list_prompt_todos = list_prompt_tasks
set_active_todo = set_active_task
complete_todo = complete_task
bootstrap_todos_from_tasks = bootstrap_tasks_from_milestone

