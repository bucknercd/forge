"""CLI tests for workflow UX (status, milestone-list/show, task-complete)."""

from __future__ import annotations

import json

from forge.cli import ForgeCLI, main
from forge.paths import Paths
from forge.prompt_task_state import (
    PromptTask,
    PromptTaskState,
    save_prompt_task_state,
)
from tests.forge_test_project import configure_project, forge_block


def _minimal_milestones() -> str:
    return f"""
# Milestones

## Milestone 1: Alpha
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("WF_UX")}

## Milestone 2: Beta
- **Objective**: O2
- **Scope**: S2
- **Validation**: V2
{forge_block("WF_UX2")}
"""


def _configure_valid_project(tmp_path) -> None:
    """configure_project + files required by Paths.project_validation()."""
    Paths.refresh(tmp_path)
    configure_project(tmp_path, _minimal_milestones())
    Paths.VISION_FILE.write_text("Vision\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()


def test_forge_status_mentions_workflow_and_milestones(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _configure_valid_project(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "status"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "Workflow" in out
    assert "Milestone 1" in out or "1." in out
    assert "Suggested next" in out


def test_forge_milestone_list_shows_workflow_column(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _configure_valid_project(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "milestone-list"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "workflow:" in out
    assert "legacy state:" in out


def test_forge_milestone_show_positional_and_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _configure_valid_project(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "milestone-show", "1"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "Milestone 1:" in out
    assert "Workflow:" in out
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["forge", "milestone-show", "--milestone", "2"])
    assert main() == 0
    out2 = capsys.readouterr().out
    assert "Milestone 2:" in out2


def test_forge_milestone_show_missing_id_exits_2(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["forge", "milestone-show"])
    assert main() == 2
    err = capsys.readouterr().err
    assert "milestone id" in err.lower()


def test_task_complete_completes_active_and_prints_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _configure_valid_project(tmp_path)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=7,
            tasks=[
                PromptTask(
                    id=7,
                    title="Do the thing",
                    objective="",
                    status="active",
                    milestone_id=1,
                    task_id=3,
                )
            ],
        )
    )
    monkeypatch.setattr("sys.argv", ["forge", "task-complete"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "Completed:" in out
    assert "Do the thing" in out
    assert "milestone 1" in out
    assert "milestone-local task 3" in out


def test_task_complete_no_active_helpful_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _configure_valid_project(tmp_path)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=None,
            tasks=[
                PromptTask(
                    id=1,
                    title="P",
                    objective="",
                    status="pending",
                    milestone_id=1,
                    task_id=1,
                )
            ],
        )
    )
    monkeypatch.setattr("sys.argv", ["forge", "task-complete"])
    assert main() == 1
    out = capsys.readouterr().out
    assert "No active task" in out
    assert "prompt-task-start" in out


def test_task_complete_json_no_active(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _configure_valid_project(tmp_path)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    save_prompt_task_state(
        PromptTaskState(version=1, active_task_id=None, tasks=[])
    )
    monkeypatch.setattr("sys.argv", ["forge", "task-complete", "--json"])
    assert main() == 1
    body = json.loads(capsys.readouterr().out)
    assert body.get("ok") is False
    assert body.get("error") == "no_active_task"


def test_infer_milestone_workflow_label_module(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _configure_valid_project(tmp_path)
    from forge.task_service import expand_milestone_to_tasks

    expand_milestone_to_tasks(milestone_id=1, force=True)
    from forge.workflow_ux import infer_milestone_workflow_label

    assert infer_milestone_workflow_label(1) == "not_synced"
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=1,
            tasks=[
                PromptTask(
                    id=1,
                    title="T",
                    objective="",
                    status="active",
                    milestone_id=1,
                    task_id=1,
                )
            ],
        )
    )
    assert infer_milestone_workflow_label(1) == "in_progress"


def test_task_list_json_includes_workflow_fields(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _configure_valid_project(tmp_path)
    from forge.task_service import expand_milestone_to_tasks

    expand_milestone_to_tasks(milestone_id=1, force=True)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=None,
            tasks=[
                PromptTask(
                    id=9,
                    title="Synced",
                    objective="",
                    status="pending",
                    milestone_id=1,
                    task_id=1,
                )
            ],
        )
    )
    monkeypatch.setattr(
        "sys.argv", ["forge", "task-list", "--milestone", "1", "--json"]
    )
    assert main() == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows
    assert rows[0].get("prompt_task_id") == 9
    assert rows[0].get("workflow_status") == "pending"
