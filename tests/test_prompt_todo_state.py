from __future__ import annotations

import json

from forge.paths import Paths
from forge.prompt_task_state import (
    TASK_STATUS_ACTIVE,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_PENDING,
    PromptTask,
    PromptTaskState,
    bootstrap_tasks_from_milestone,
    complete_task,
    load_prompt_task_state,
    save_prompt_task_state,
    set_active_task,
    task_state_path,
)
from tests.forge_test_project import configure_project, forge_block
from forge.task_service import expand_milestone_to_tasks


def test_load_default_state_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    state = load_prompt_task_state()
    assert state.active_task_id is None
    assert state.tasks == []


def test_save_and_load_round_trip_single_active(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    st = PromptTaskState(
        version=1,
        active_task_id=2,
        tasks=[
            PromptTask(id=1, title="a", objective="oa", status=TASK_STATUS_ACTIVE),
            PromptTask(id=2, title="b", objective="ob", status=TASK_STATUS_PENDING),
        ],
    )
    save_prompt_task_state(st)
    loaded = load_prompt_task_state()
    assert loaded.active_task_id == 2
    s = {t.id: t.status for t in loaded.tasks}
    assert s[1] == TASK_STATUS_PENDING
    assert s[2] == TASK_STATUS_ACTIVE


def test_set_active_task_enforces_one_active(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=1,
            tasks=[
                PromptTask(id=1, title="a", objective="oa", status=TASK_STATUS_ACTIVE),
                PromptTask(id=2, title="b", objective="ob", status=TASK_STATUS_PENDING),
            ],
        )
    )
    out = set_active_task(2)
    assert out.active_task_id == 2
    s = {t.id: t.status for t in out.tasks}
    assert s[1] == TASK_STATUS_PENDING
    assert s[2] == TASK_STATUS_ACTIVE


def test_complete_task_is_explicit_and_clears_active(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=1,
            tasks=[
                PromptTask(id=1, title="a", objective="oa", status=TASK_STATUS_ACTIVE),
                PromptTask(id=2, title="b", objective="ob", status=TASK_STATUS_PENDING),
            ],
        )
    )
    out = complete_task(1)
    assert out.active_task_id is None
    s = {t.id: t.status for t in out.tasks}
    assert s[1] == TASK_STATUS_COMPLETED
    assert s[2] == TASK_STATUS_PENDING


def test_corrupted_state_file_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    task_state_path().write_text("{ bad json", encoding="utf-8")
    out = load_prompt_task_state()
    assert out.tasks == []
    assert out.active_task_id is None


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
    state = bootstrap_tasks_from_milestone(1, force=True)
    assert len(state.tasks) >= 1
    assert state.active_task_id is not None
    assert any(t.status == TASK_STATUS_ACTIVE for t in state.tasks)


def test_bootstrap_does_not_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=99,
            tasks=[PromptTask(id=99, title="manual", objective="manual", status=TASK_STATUS_ACTIVE)],
        )
    )
    state = bootstrap_tasks_from_milestone(1, force=False)
    assert state.active_task_id == 99
    assert len(state.tasks) == 1

