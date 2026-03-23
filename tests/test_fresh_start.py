from __future__ import annotations

import os
from pathlib import Path

from forge.cli import ForgeCLI
from forge.executor import Executor
from forge.fresh_start import reset_generated_only
from forge.paths import Paths
from forge.execution.plan import ExecutionPlanBuilder
from forge.planner import DeterministicPlanner
from forge.task_service import expand_milestone_to_tasks, list_tasks
from tests.forge_test_project import configure_project


_PY_MILESTONES = """
# Milestones

## Milestone 1: Python App
- **Objective**: Write a Python todo CLI.
- **Scope**: src/ and tests/
- **Validation**: python ok
- **Forge Actions**:
  - write_file src/todo_cli.py | def main():\\n    return 'py'\\n
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements PY_OK
"""

_GO_MILESTONES = """
# Milestones

## Milestone 1: Go App
- **Objective**: Write a Go main program.
- **Scope**: src/ and tests/
- **Validation**: go ok
- **Forge Actions**:
  - write_file src/main.go | package main\\n\\nfunc main() {\\n}\\n
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements GO_OK
"""


def _apply_task1_for_current_milestone(tmp_path: Path) -> None:
    prev = Executor.save_reviewed_plan_for_task(
        1, 1, planner=DeterministicPlanner()
    )
    assert prev.get("ok") is True, prev
    plan_id = prev["plan_id"]
    applied = Executor.apply_reviewed_plan(plan_id)
    assert applied.get("apply_ok") is True, applied


def test_fresh_start_generated_only_clears_previous_python_app_state(tmp_path):
    Paths.refresh(tmp_path)
    configure_project(tmp_path, _PY_MILESTONES)

    # Expand + apply to create prior generated artifacts.
    expand_milestone_to_tasks(milestone_id=1, force=True)
    _apply_task1_for_current_milestone(tmp_path)
    assert (tmp_path / "src" / "todo_cli.py").exists()
    assert (Paths.SYSTEM_DIR / "tasks" / "m1.json").exists()

    # Create some dummy milestone state to verify it is removed.
    (Paths.SYSTEM_DIR / "milestone_state.json").write_text(
        '{"1": {"status": "completed"}}', encoding="utf-8"
    )

    # Fresh start: clear state + remove generated python residues.
    wiped = reset_generated_only()
    assert wiped.get("tasks_removed") is True
    assert wiped.get("reviewed_plans_removed") is True
    assert wiped.get("results_removed") is True
    assert (Paths.SYSTEM_DIR / "milestone_state.json").exists() is False
    assert (tmp_path / "src" / "todo_cli.py").exists() is False

    # Now switch milestone list to Go and ensure task expansion reflects only Go.
    Paths.MILESTONES_FILE.write_text(_GO_MILESTONES, encoding="utf-8")
    expand_milestone_to_tasks(milestone_id=1, force=True)
    tasks = list_tasks(1)
    assert tasks
    task_blob = " ".join(
        " ".join([t.objective, t.summary] + list(t.forge_actions))
        for t in tasks
    ).lower()
    assert "todo_cli.py" not in task_blob
    assert "main.go" in task_blob

    _apply_task1_for_current_milestone(tmp_path)
    assert (tmp_path / "src" / "main.go").exists()
    assert not (tmp_path / "src" / "todo_cli.py").exists()

