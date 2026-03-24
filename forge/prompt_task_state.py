"""
Task-first compatibility facade for prompt-task state.

Preferred user-facing terminology is "task". This module re-exports the
Phase-1 state model implemented in prompt_todo_state without breaking imports.
"""

from __future__ import annotations

from forge.prompt_todo_state import (
    PromptTodo as PromptTask,
    PromptTodoState as PromptTaskState,
    TODO_STATUS_ACTIVE as TASK_STATUS_ACTIVE,
    TODO_STATUS_COMPLETED as TASK_STATUS_COMPLETED,
    TODO_STATUS_PENDING as TASK_STATUS_PENDING,
    bootstrap_tasks_from_milestone,
    complete_task,
    list_prompt_tasks,
    load_prompt_task_state,
    save_prompt_task_state,
    set_active_task,
    todo_state_path as task_state_path,
)

