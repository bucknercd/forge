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

TODO_STATUS_PENDING = "pending"
TODO_STATUS_ACTIVE = "active"
TODO_STATUS_COMPLETED = "completed"
_ALLOWED_STATUSES = {
    TODO_STATUS_PENDING,
    TODO_STATUS_ACTIVE,
    TODO_STATUS_COMPLETED,
}
_STATE_VERSION = 1


@dataclass
class PromptTodo:
    id: int
    title: str
    objective: str
    status: str = TODO_STATUS_PENDING
    milestone_id: int | None = None
    task_id: int | None = None

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PromptTodo":
        status = str(raw.get("status", TODO_STATUS_PENDING)).strip().lower()
        if status not in _ALLOWED_STATUSES:
            status = TODO_STATUS_PENDING
        return PromptTodo(
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
class PromptTodoState:
    version: int
    active_todo_id: int | None
    todos: list[PromptTodo]

    def to_dict(self) -> dict[str, Any]:
        # Persist task-first keys; keep legacy aliases in loader only.
        return {
            "version": self.version,
            "active_task_id": self.active_todo_id,
            "tasks": [asdict(t) for t in self.todos],
        }


def todo_state_path() -> Path:
    return Paths.SYSTEM_DIR / "prompt_tasks.json"


def _legacy_todo_state_path() -> Path:
    return Paths.SYSTEM_DIR / "prompt_todos.json"


def default_state() -> PromptTodoState:
    return PromptTodoState(version=_STATE_VERSION, active_todo_id=None, todos=[])


def _normalize_single_active(state: PromptTodoState) -> PromptTodoState:
    active = state.active_todo_id
    if active is not None and all(t.id != active for t in state.todos):
        active = None

    # Enforce exactly one active or none.
    seen_active = False
    normalized: list[PromptTodo] = []
    for t in state.todos:
        st = t.status if t.status in _ALLOWED_STATUSES else TODO_STATUS_PENDING
        if active is not None and t.id == active:
            st = TODO_STATUS_ACTIVE
            seen_active = True
        elif st == TODO_STATUS_ACTIVE:
            st = TODO_STATUS_PENDING
        normalized.append(
            PromptTodo(
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
    return PromptTodoState(version=_STATE_VERSION, active_todo_id=active, todos=normalized)


def load_todo_state() -> PromptTodoState:
    path = todo_state_path()
    if not path.exists() and _legacy_todo_state_path().exists():
        path = _legacy_todo_state_path()
    if not path.exists():
        return default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        tasks_blob = raw.get("tasks")
        if tasks_blob is None:
            tasks_blob = raw.get("todos", [])
        todos = [PromptTodo.from_dict(t) for t in list(tasks_blob)]
        active_raw = raw.get("active_task_id")
        if active_raw is None:
            active_raw = raw.get("active_todo_id")
        state = PromptTodoState(
            version=int(raw.get("version", _STATE_VERSION)),
            active_todo_id=(
                int(active_raw)
                if active_raw is not None
                else None
            ),
            todos=todos,
        )
    except Exception:
        # Keep startup resilient if file is partially written/corrupted.
        return default_state()
    return _normalize_single_active(state)


def save_todo_state(state: PromptTodoState) -> None:
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    path = todo_state_path()
    normalized = _normalize_single_active(state)
    payload = normalized.to_dict()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    # One-way migration: remove legacy path after successful canonical write.
    legacy = _legacy_todo_state_path()
    if legacy.exists() and legacy != path:
        try:
            legacy.unlink()
        except OSError:
            pass


def list_prompt_todos() -> list[PromptTodo]:
    return list(load_todo_state().todos)


def set_active_todo(todo_id: int) -> PromptTodoState:
    state = load_todo_state()
    found = False
    out: list[PromptTodo] = []
    for t in state.todos:
        if t.id == todo_id:
            if t.status == TODO_STATUS_COMPLETED:
                raise ValueError(f"Todo {todo_id} is already completed.")
            out.append(
                PromptTodo(
                    id=t.id,
                    title=t.title,
                    objective=t.objective,
                    status=TODO_STATUS_ACTIVE,
                    milestone_id=t.milestone_id,
                    task_id=t.task_id,
                )
            )
            found = True
        else:
            st = TODO_STATUS_PENDING if t.status == TODO_STATUS_ACTIVE else t.status
            out.append(
                PromptTodo(
                    id=t.id,
                    title=t.title,
                    objective=t.objective,
                    status=st,
                    milestone_id=t.milestone_id,
                    task_id=t.task_id,
                )
            )
    if not found:
        raise ValueError(f"Unknown todo id {todo_id}.")
    new_state = PromptTodoState(version=_STATE_VERSION, active_todo_id=todo_id, todos=out)
    save_todo_state(new_state)
    return load_todo_state()


def complete_todo(todo_id: int) -> PromptTodoState:
    """
    Explicit completion path: todo completion only happens via this call/CLI command.
    """
    state = load_todo_state()
    found = False
    out: list[PromptTodo] = []
    active = state.active_todo_id
    for t in state.todos:
        if t.id == todo_id:
            found = True
            out.append(
                PromptTodo(
                    id=t.id,
                    title=t.title,
                    objective=t.objective,
                    status=TODO_STATUS_COMPLETED,
                    milestone_id=t.milestone_id,
                    task_id=t.task_id,
                )
            )
            if active == todo_id:
                active = None
        else:
            out.append(t)
    if not found:
        raise ValueError(f"Unknown todo id {todo_id}.")
    save_todo_state(PromptTodoState(version=_STATE_VERSION, active_todo_id=active, todos=out))
    return load_todo_state()


def bootstrap_todos_from_tasks(milestone_id: int, *, force: bool = False) -> PromptTodoState:
    """
    Reuse existing task decomposition as the initial prompt-task inventory.
    """
    state = load_todo_state()
    if state.todos and not force:
        return state
    tasks = list_tasks(milestone_id)
    todos: list[PromptTodo] = []
    for t in tasks:
        status = TODO_STATUS_COMPLETED if t.status == "completed" else TODO_STATUS_PENDING
        todos.append(
            PromptTodo(
                id=t.id,
                title=t.title,
                objective=t.objective,
                status=status,
                milestone_id=milestone_id,
                task_id=t.id,
            )
        )
    active_id = None
    for td in todos:
        if td.status == TODO_STATUS_PENDING:
            td.status = TODO_STATUS_ACTIVE
            active_id = td.id
            break
    new_state = PromptTodoState(version=_STATE_VERSION, active_todo_id=active_id, todos=todos)
    save_todo_state(new_state)
    return load_todo_state()


# Task-first aliases (preferred API names).
def load_prompt_task_state() -> PromptTodoState:
    return load_todo_state()


def save_prompt_task_state(state: PromptTodoState) -> None:
    save_todo_state(state)


def list_prompt_tasks() -> list[PromptTodo]:
    return list_prompt_todos()


def set_active_task(task_id: int) -> PromptTodoState:
    return set_active_todo(task_id)


def complete_task(task_id: int) -> PromptTodoState:
    return complete_todo(task_id)


def bootstrap_tasks_from_milestone(milestone_id: int, *, force: bool = False) -> PromptTodoState:
    return bootstrap_todos_from_tasks(milestone_id, force=force)
