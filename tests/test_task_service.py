"""Task breakdown storage and task-scoped reviewed plans."""

from __future__ import annotations

from forge.design_manager import MilestoneService
from forge.executor import Executor
from forge.paths import Paths
from forge.reviewed_plan import load_reviewed_plan
from forge.task_service import (
    expand_milestone_to_tasks,
    get_task,
    list_tasks,
    task_to_execution_milestone,
)
from tests.forge_test_project import configure_project, forge_block


def test_expand_creates_compatibility_task(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Ship
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("X")}
""",
    )
    r = expand_milestone_to_tasks(milestone_id=1)
    assert r["ok"]
    assert r["task_count"] == 1
    tasks = list_tasks(1)
    assert len(tasks) == 1
    assert tasks[0].forge_actions == MilestoneService.get_milestone(1).forge_actions


def test_task_to_execution_milestone_preserves_parent_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: M
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    expand_milestone_to_tasks(milestone_id=1)
    parent = MilestoneService.get_milestone(1)
    task = get_task(1, 1)
    assert task is not None
    shell = task_to_execution_milestone(parent, task)
    assert shell.id == 1
    assert "Ship" in shell.title or "M" in shell.title


def test_save_and_apply_task_reviewed_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Ship
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("TASK_PLAN")}
""",
    )
    expand_milestone_to_tasks(milestone_id=1)
    prev = Executor.save_reviewed_plan_for_task(1, 1)
    assert prev.get("ok"), prev
    plan_id = prev["plan_id"]
    assert plan_id.startswith("m1-t1-")
    stored = load_reviewed_plan(plan_id)
    assert stored is not None
    assert stored.get("task_id") == 1
    apply = Executor.apply_reviewed_plan_with_gates(
        plan_id,
        run_validation_gate=False,
        test_command=None,
    )
    assert apply.get("ok"), apply
    assert apply.get("task_id") == 1


def test_execution_plan_roundtrip_task_id():
    from forge.execution.models import ExecutionPlan, ActionMarkMilestoneCompleted

    p = ExecutionPlan(milestone_id=2, actions=[ActionMarkMilestoneCompleted()], task_id=3)
    d = p.to_serializable()
    assert d["task_id"] == 3
    p2 = ExecutionPlan.from_serializable(d)
    assert p2.task_id == 3
