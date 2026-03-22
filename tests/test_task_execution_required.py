"""Tasks are required for execution: auto-expand and CLI task selection."""

from __future__ import annotations

import json

from forge.cli import main
from forge.executor import Executor
from forge.paths import Paths
from forge.task_service import list_tasks, tasks_file_for_milestone
from tests.forge_test_project import compat_forge_block, configure_project


def test_preview_milestone_auto_ensures_tasks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Auto
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("AUTO")}
""",
    )
    assert not tasks_file_for_milestone(1).exists()
    r = Executor.preview_milestone(1, task_id=1)
    assert r["ok"] is True
    assert tasks_file_for_milestone(1).exists()
    assert list_tasks(1)


def test_milestone_preview_json_requires_task_selection_without_task(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr()
    (tmp_path / "docs" / "milestones.md").write_text(
        f"""
# Milestones

## Milestone 1: Sel
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("SEL")}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["forge", "milestone-preview", "1", "--json"])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload.get("requires_task_selection") is True
    assert payload.get("tasks")
    assert payload["milestone_id"] == 1
