from __future__ import annotations

import json

from forge.paths import Paths
from forge.prompt_todo_state import (
    TODO_STATUS_ACTIVE,
    TODO_STATUS_COMPLETED,
    TODO_STATUS_PENDING,
    PromptTodo,
    PromptTodoState,
    bootstrap_todos_from_tasks,
    complete_todo,
    load_todo_state,
    save_todo_state,
    set_active_todo,
    todo_state_path,
)
from tests.forge_test_project import configure_project, forge_block
from forge.task_service import expand_milestone_to_tasks


def test_load_default_state_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    state = load_todo_state()
    assert state.active_todo_id is None
    assert state.todos == []


def test_save_and_load_round_trip_single_active(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    st = PromptTodoState(
        version=1,
        active_todo_id=2,
        todos=[
            PromptTodo(id=1, title="a", objective="oa", status=TODO_STATUS_ACTIVE),
            PromptTodo(id=2, title="b", objective="ob", status=TODO_STATUS_PENDING),
        ],
    )
    save_todo_state(st)
    loaded = load_todo_state()
    assert loaded.active_todo_id == 2
    s = {t.id: t.status for t in loaded.todos}
    assert s[1] == TODO_STATUS_PENDING
    assert s[2] == TODO_STATUS_ACTIVE


def test_set_active_todo_enforces_one_active(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_todo_state(
        PromptTodoState(
            version=1,
            active_todo_id=1,
            todos=[
                PromptTodo(id=1, title="a", objective="oa", status=TODO_STATUS_ACTIVE),
                PromptTodo(id=2, title="b", objective="ob", status=TODO_STATUS_PENDING),
            ],
        )
    )
    out = set_active_todo(2)
    assert out.active_todo_id == 2
    s = {t.id: t.status for t in out.todos}
    assert s[1] == TODO_STATUS_PENDING
    assert s[2] == TODO_STATUS_ACTIVE


def test_complete_todo_is_explicit_and_clears_active(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_todo_state(
        PromptTodoState(
            version=1,
            active_todo_id=1,
            todos=[
                PromptTodo(id=1, title="a", objective="oa", status=TODO_STATUS_ACTIVE),
                PromptTodo(id=2, title="b", objective="ob", status=TODO_STATUS_PENDING),
            ],
        )
    )
    out = complete_todo(1)
    assert out.active_todo_id is None
    s = {t.id: t.status for t in out.todos}
    assert s[1] == TODO_STATUS_COMPLETED
    assert s[2] == TODO_STATUS_PENDING


def test_corrupted_state_file_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    todo_state_path().write_text("{ bad json", encoding="utf-8")
    out = load_todo_state()
    assert out.todos == []
    assert out.active_todo_id is None


def test_bootstrap_from_tasks_reuses_existing_task_logic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Prompt workflow
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("PROMPT_TODO_OK")}
""",
    )
    res = expand_milestone_to_tasks(milestone_id=1, force=True)
    assert res.get("ok")
    state = bootstrap_todos_from_tasks(1, force=True)
    assert len(state.todos) >= 1
    assert state.active_todo_id is not None
    assert any(t.status == TODO_STATUS_ACTIVE for t in state.todos)


def test_bootstrap_does_not_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_todo_state(
        PromptTodoState(
            version=1,
            active_todo_id=99,
            todos=[PromptTodo(id=99, title="manual", objective="manual", status=TODO_STATUS_ACTIVE)],
        )
    )
    state = bootstrap_todos_from_tasks(1, force=False)
    assert state.active_todo_id == 99
    assert len(state.todos) == 1

