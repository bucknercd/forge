from __future__ import annotations

import pytest

from forge.paths import Paths
from forge.prompt_task_state import (
    TASK_STATUS_ACTIVE,
    TASK_STATUS_COMPLETED,
    PromptTask,
    PromptTaskState,
    complete_task,
    save_prompt_task_state,
    sync_prompt_tasks_from_milestone,
)
from forge.task_service import Task, save_tasks, tasks_file_for_milestone


def _mk_source_task(
    task_id: int, *, milestone_id: int = 1, title: str | None = None, status: str = "not_started"
) -> Task:
    return Task(
        id=task_id,
        milestone_id=milestone_id,
        title=title or f"Task {task_id} title",
        objective=f"Task {task_id} objective",
        summary=f"Task {task_id} summary",
        depends_on=[task_id - 1] if task_id > 1 else [],
        validation="V",
        done_when="D",
        status=status,
        forge_actions=[],
        forge_validation=[],
    )


def test_bootstrap_from_empty_state_projects_source_tasks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2)])
    state = sync_prompt_tasks_from_milestone(1)
    assert [t.task_id for t in state.tasks] == [1, 2]
    assert state.active_task_id is not None
    assert len([t for t in state.tasks if t.status == TASK_STATUS_ACTIVE]) == 1


def test_repeated_sync_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2)])
    s1 = sync_prompt_tasks_from_milestone(1)
    s2 = sync_prompt_tasks_from_milestone(1)
    assert s1.to_dict() == s2.to_dict()
    s3 = sync_prompt_tasks_from_milestone(1)
    assert s2.to_dict() == s3.to_dict()


def test_source_linkage_is_present_and_preserved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2)])
    s1 = sync_prompt_tasks_from_milestone(1)
    ids_before = {t.task_id: t.id for t in s1.tasks}
    save_tasks(1, [_mk_source_task(1, title="Updated title"), _mk_source_task(2)])
    s2 = sync_prompt_tasks_from_milestone(1)
    ids_after = {t.task_id: t.id for t in s2.tasks}
    assert ids_after == ids_before
    assert all(t.milestone_id == 1 for t in s2.tasks)


def test_ordering_preserved_across_sync(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(2), _mk_source_task(1), _mk_source_task(3)])
    state = sync_prompt_tasks_from_milestone(1)
    assert [t.task_id for t in state.tasks[:3]] == [2, 1, 3]


def test_single_active_invariant_after_sync(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2)])
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=999,
            tasks=[
                PromptTask(id=10, title="a", objective="oa", status=TASK_STATUS_ACTIVE, milestone_id=1, task_id=1),
                PromptTask(id=11, title="b", objective="ob", status=TASK_STATUS_ACTIVE, milestone_id=1, task_id=2),
            ],
        )
    )
    state = sync_prompt_tasks_from_milestone(1)
    assert len([t for t in state.tasks if t.status == TASK_STATUS_ACTIVE]) == 1


def test_completed_tasks_preserved_across_reconcile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2)])
    first = sync_prompt_tasks_from_milestone(1)
    t1_id = next(t.id for t in first.tasks if t.task_id == 1)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=first.active_task_id,
            tasks=[
                PromptTask(id=t.id, title=t.title, objective=t.objective, status=t.status, milestone_id=t.milestone_id, task_id=t.task_id)
                for t in first.tasks
            ],
        )
    )
    complete_task(t1_id)
    state = sync_prompt_tasks_from_milestone(1)
    t1 = next(t for t in state.tasks if t.id == t1_id)
    assert t1.status == TASK_STATUS_COMPLETED


def test_active_task_preserved_when_still_valid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2)])
    state = sync_prompt_tasks_from_milestone(1)
    second = next(t for t in state.tasks if t.task_id == 2)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=second.id,
            tasks=[
                PromptTask(
                    id=t.id,
                    title=t.title,
                    objective=t.objective,
                    status=TASK_STATUS_ACTIVE if t.id == second.id else t.status,
                    milestone_id=t.milestone_id,
                    task_id=t.task_id,
                )
                for t in state.tasks
            ],
        )
    )
    synced = sync_prompt_tasks_from_milestone(1)
    assert synced.active_task_id == second.id


def test_new_source_tasks_added_without_duplicates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2)])
    sync_prompt_tasks_from_milestone(1)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2), _mk_source_task(3)])
    synced = sync_prompt_tasks_from_milestone(1)
    source_linked = [(t.milestone_id, t.task_id) for t in synced.tasks if t.milestone_id == 1 and t.task_id is not None]
    assert source_linked.count((1, 1)) == 1
    assert source_linked.count((1, 2)) == 1
    assert source_linked.count((1, 3)) == 1


def test_legacy_todo_shim_compatibility_still_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1)])
    from forge.prompt_todo_state import bootstrap_todos_from_tasks

    state = bootstrap_todos_from_tasks(1, force=True)
    assert len(state.tasks) == 1
    assert state.tasks[0].milestone_id == 1


def test_malformed_source_task_data_fails_explicitly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    tasks_file_for_milestone(1).parent.mkdir(parents=True, exist_ok=True)
    tasks_file_for_milestone(1).write_text('{"version":1,"milestone_id":1,"tasks":[{"id":"bad"}]}', encoding="utf-8")
    with pytest.raises(ValueError):
        sync_prompt_tasks_from_milestone(1)


def test_duplicate_source_task_ids_raise_value_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    tasks_file_for_milestone(1).parent.mkdir(parents=True, exist_ok=True)
    tasks_file_for_milestone(1).write_text(
        (
            '{"version":1,"milestone_id":1,"tasks":['
            '{"id":1,"title":"a","objective":"oa","summary":"sa","depends_on":[],"validation":"V","done_when":"D","status":"not_started","forge_actions":[],"forge_validation":[]},'
            '{"id":1,"title":"b","objective":"ob","summary":"sb","depends_on":[],"validation":"V","done_when":"D","status":"not_started","forge_actions":[],"forge_validation":[]}'
            "]}"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate task id"):
        sync_prompt_tasks_from_milestone(1)


def test_force_sync_removes_unmatched_historical_rows_for_milestone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    save_tasks(1, [_mk_source_task(1), _mk_source_task(2)])
    baseline = sync_prompt_tasks_from_milestone(1)
    baseline_ids = {t.id for t in baseline.tasks if t.milestone_id == 1}
    stale_id = max(baseline_ids) + 100
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=baseline.active_task_id,
            tasks=[
                PromptTask(
                    id=t.id,
                    title=t.title,
                    objective=t.objective,
                    status=t.status,
                    milestone_id=t.milestone_id,
                    task_id=t.task_id,
                )
                for t in baseline.tasks
            ]
            + [
                PromptTask(
                    id=stale_id,
                    title="old unmatched",
                    objective="old unmatched objective",
                    status=TASK_STATUS_COMPLETED,
                    milestone_id=1,
                    task_id=999,
                )
            ],
        )
    )
    non_force = sync_prompt_tasks_from_milestone(1, force=False)
    assert any(t.id == stale_id for t in non_force.tasks)
    forced = sync_prompt_tasks_from_milestone(1, force=True)
    assert all(t.id != stale_id for t in forced.tasks)
