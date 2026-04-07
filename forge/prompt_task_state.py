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


def _next_prompt_task_id(tasks: list[PromptTask]) -> int:
    max_id = 0
    for t in tasks:
        if t.id > max_id:
            max_id = t.id
    return max_id + 1


def _project_source_tasks(milestone_id: int) -> list[PromptTask]:
    """
    Deterministically project source milestone task rows into prompt-task candidates.

    Raises ValueError on malformed source task rows so sync can fail explicitly.
    """
    try:
        source_items = list_tasks(milestone_id)
    except Exception as exc:
        raise ValueError(
            f"Failed to load source tasks for milestone {milestone_id}: {exc}"
        ) from exc
    out: list[PromptTask] = []
    seen_source_ids: set[int] = set()
    for source in source_items:
        source_id = int(source.id)
        if source_id <= 0:
            raise ValueError(
                f"Malformed source task for milestone {milestone_id}: id must be > 0."
            )
        if source_id in seen_source_ids:
            raise ValueError(
                f"Malformed source task data for milestone {milestone_id}: duplicate task id {source_id}."
            )
        seen_source_ids.add(source_id)
        out.append(
            PromptTask(
                id=0,  # assigned during reconcile
                title=str(source.title or ""),
                objective=str(source.objective or ""),
                status=(
                    TASK_STATUS_COMPLETED
                    if str(source.status).strip().lower() == "completed"
                    else TASK_STATUS_PENDING
                ),
                milestone_id=milestone_id,
                task_id=source_id,
            )
        )
    return out


def _reconcile_existing_and_projected_tasks(
    state: PromptTaskState,
    milestone_id: int,
    projected: list[PromptTask],
    *,
    force: bool = False,
) -> tuple[list[PromptTask], list[int]]:
    """
    Merge projected source tasks with existing prompt-task state.

    - Match by (milestone_id, task_id) first.
    - Preserve existing ids and completed history when safe.
    - Keep orphaned historical rows for this milestone unless force=True.
    - Return merged tasks plus source-order ids for active-task fallback.
    """
    existing_all = list(state.tasks)
    existing_for_milestone = [t for t in existing_all if t.milestone_id == milestone_id]
    existing_other = [t for t in existing_all if t.milestone_id != milestone_id]

    by_source_key: dict[int, PromptTask] = {}
    for t in existing_for_milestone:
        if t.task_id is None:
            continue
        by_source_key.setdefault(int(t.task_id), t)

    out_for_milestone: list[PromptTask] = []
    source_order_ids: list[int] = []
    used_existing_ids: set[int] = set()

    next_id = _next_prompt_task_id(existing_all)
    for candidate in projected:
        matched = by_source_key.get(int(candidate.task_id or 0))
        if matched is not None:
            used_existing_ids.add(matched.id)
            merged_status = candidate.status
            if matched.status == TASK_STATUS_COMPLETED:
                merged_status = TASK_STATUS_COMPLETED
            elif matched.status == TASK_STATUS_ACTIVE and candidate.status != TASK_STATUS_COMPLETED:
                merged_status = TASK_STATUS_ACTIVE
            elif candidate.status != TASK_STATUS_COMPLETED:
                merged_status = TASK_STATUS_PENDING
            out_for_milestone.append(
                PromptTask(
                    id=matched.id,
                    title=candidate.title,
                    objective=candidate.objective,
                    status=merged_status,
                    milestone_id=milestone_id,
                    task_id=candidate.task_id,
                )
            )
            source_order_ids.append(matched.id)
            continue

        assigned_id = next_id
        next_id += 1
        out_for_milestone.append(
            PromptTask(
                id=assigned_id,
                title=candidate.title,
                objective=candidate.objective,
                status=candidate.status,
                milestone_id=milestone_id,
                task_id=candidate.task_id,
            )
        )
        source_order_ids.append(assigned_id)

    if not force:
        for old in existing_for_milestone:
            if old.id in used_existing_ids:
                continue
            preserved_status = (
                TASK_STATUS_COMPLETED
                if old.status == TASK_STATUS_COMPLETED
                else TASK_STATUS_PENDING
            )
            out_for_milestone.append(
                PromptTask(
                    id=old.id,
                    title=old.title,
                    objective=old.objective,
                    status=preserved_status,
                    milestone_id=old.milestone_id,
                    task_id=old.task_id,
                )
            )

    return existing_other + out_for_milestone, source_order_ids


def _enforce_post_reconcile_single_active(
    tasks: list[PromptTask],
    *,
    preferred_active_id: int | None,
    source_order_ids: list[int],
) -> PromptTaskState:
    by_id = {t.id: t for t in tasks}
    active_id = preferred_active_id
    if active_id is not None:
        active_task = by_id.get(active_id)
        if active_task is None or active_task.status == TASK_STATUS_COMPLETED:
            active_id = None

    if active_id is None:
        for tid in source_order_ids:
            t = by_id.get(tid)
            if t is not None and t.status == TASK_STATUS_PENDING:
                active_id = tid
                break

    if active_id is None:
        for t in tasks:
            if t.status == TASK_STATUS_PENDING:
                active_id = t.id
                break

    normalized: list[PromptTask] = []
    for t in tasks:
        st = t.status
        if t.id == active_id and t.status != TASK_STATUS_COMPLETED:
            st = TASK_STATUS_ACTIVE
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
    return _normalize_single_active(
        PromptTaskState(version=_STATE_VERSION, active_task_id=active_id, tasks=normalized)
    )


def sync_prompt_tasks_from_milestone(
    milestone_id: int, *, force: bool = False
) -> PromptTaskState:
    """
    Deterministically reconcile prompt-task state from source milestone tasks.
    """
    state = load_prompt_task_state()
    projected = _project_source_tasks(milestone_id)
    merged_tasks, source_order_ids = _reconcile_existing_and_projected_tasks(
        state, milestone_id, projected, force=force
    )
    next_state = _enforce_post_reconcile_single_active(
        merged_tasks,
        preferred_active_id=state.active_task_id,
        source_order_ids=source_order_ids,
    )
    save_prompt_task_state(next_state)
    return load_prompt_task_state()


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
    return sync_prompt_tasks_from_milestone(milestone_id, force=force)


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
sync_prompt_todos_from_tasks = sync_prompt_tasks_from_milestone

