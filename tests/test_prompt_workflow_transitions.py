from __future__ import annotations

import json

from forge.cli import main
from forge.paths import Paths
from forge.prompt_compiler import generate_prompt_artifact
from forge.prompt_task_state import (
    PromptTask,
    PromptTaskState,
    prompt_workflow_history_path,
    save_prompt_task_state,
)


def _seed_prompt_tasks(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.initialize_project()
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=None,
            tasks=[
                PromptTask(
                    id=1,
                    title="Task one",
                    objective="Implement first task",
                    status="pending",
                    milestone_id=1,
                    task_id=1,
                ),
                PromptTask(
                    id=2,
                    title="Task two",
                    objective="Implement second task",
                    status="completed",
                    milestone_id=1,
                    task_id=2,
                ),
            ],
        )
    )


def test_prompt_task_start_succeeds_for_pending_task(tmp_path, monkeypatch, capsys):
    _seed_prompt_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["forge", "prompt-task-start", "--id", "1", "--json"])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is True
    assert payload.get("started_task_id") == 1
    assert payload.get("active_task_id") == 1


def test_prompt_task_start_sets_active_without_completing(tmp_path, monkeypatch):
    _seed_prompt_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["forge", "prompt-task-start", "--id", "1"])
    assert main() == 0
    data = json.loads((tmp_path / ".system" / "prompt_tasks.json").read_text(encoding="utf-8"))
    row = next(t for t in data["tasks"] if t["id"] == 1)
    assert data["active_task_id"] == 1
    assert row["status"] == "active"


def test_prompt_task_start_unknown_id_fails(tmp_path, monkeypatch, capsys):
    _seed_prompt_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["forge", "prompt-task-start", "--id", "999"])
    assert main() == 1
    out = capsys.readouterr().out
    assert "Unknown task id 999." in out


def test_prompt_task_start_completed_task_fails(tmp_path, monkeypatch, capsys):
    _seed_prompt_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["forge", "prompt-task-start", "--id", "2"])
    assert main() == 1
    out = capsys.readouterr().out
    assert "already completed" in out


def test_prompt_task_start_records_provenance(tmp_path, monkeypatch):
    _seed_prompt_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["forge", "prompt-task-start", "--id", "1"])
    assert main() == 0
    path = prompt_workflow_history_path()
    assert path.exists()
    last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert last["event"] == "task_started"
    assert last["task_id"] == 1
    assert last["milestone_id"] == 1
    assert last["status_before"] == "pending"
    assert last["status_after"] == "active"
    assert last["source"] == "forge_cli"


def test_prompt_task_complete_behavior_unchanged(tmp_path, monkeypatch):
    _seed_prompt_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["forge", "prompt-task-complete", "--id", "1"])
    assert main() == 0
    data = json.loads((tmp_path / ".system" / "prompt_tasks.json").read_text(encoding="utf-8"))
    row = next(t for t in data["tasks"] if t["id"] == 1)
    assert row["status"] == "completed"


def test_prompt_generate_behavior_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.REQUIREMENTS_FILE.write_text("# Requirements\n", encoding="utf-8")
    Paths.ARCHITECTURE_FILE.write_text("# Architecture\n", encoding="utf-8")
    Paths.VISION_FILE.write_text("Vision\n", encoding="utf-8")
    Paths.MILESTONES_FILE.write_text(
        (
            "# Milestones\n\n"
            "## Milestone 1: X\n"
            "- **Objective**: O\n"
            "- **Scope**: S\n"
            "- **Validation**: V\n"
        ),
        encoding="utf-8",
    )
    tasks_dir = Paths.SYSTEM_DIR / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "m1.json").write_text(
        json.dumps(
            {
                "version": 1,
                "milestone_id": 1,
                "tasks": [
                    {
                        "id": 1,
                        "title": "Task one",
                        "objective": "Obj",
                        "summary": "Sum",
                        "depends_on": [],
                        "files_allowed": None,
                        "validation": "V",
                        "done_when": "D",
                        "status": "not_started",
                        "milestone_context": "",
                        "forge_actions": [],
                        "forge_validation": [],
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    out = generate_prompt_artifact(1, 1)
    assert out["prompt_path"].endswith(".system/prompts/m1-t1.prompt.txt")
