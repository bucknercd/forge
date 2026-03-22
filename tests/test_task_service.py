"""Task breakdown storage and task-scoped reviewed plans."""

from __future__ import annotations

import json

from forge.design_manager import MilestoneService
from forge.executor import Executor
from forge.paths import Paths
from forge.reviewed_plan import load_reviewed_plan
from forge.task_service import (
    Task,
    expand_milestone_to_tasks,
    get_task,
    list_tasks,
    save_tasks,
    split_actions_into_tasks,
    task_to_execution_milestone,
    tasks_file_for_milestone,
    validate_task_list,
)
from tests.forge_test_project import configure_project, forge_block


def test_expand_creates_multiple_tasks_from_typical_milestone(tmp_path, monkeypatch):
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
    assert r["task_count"] >= 2
    assert r.get("expansion_mode") == "deterministic_multi"
    tasks = list_tasks(1)
    assert len(tasks) >= 2
    parent = MilestoneService.get_milestone(1)
    combined = []
    for t in sorted(tasks, key=lambda x: x.id):
        combined.extend(t.forge_actions)
    assert combined == parent.forge_actions
    last = tasks[-1]
    assert any(a.strip() == "mark_milestone_completed" for a in last.forge_actions)


def test_expand_compat_when_single_action_without_mark(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Solo
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | only
- **Forge Validation**:
  - file_contains requirements only
""",
    )
    r = expand_milestone_to_tasks(milestone_id=1)
    assert r["ok"]
    assert r["task_count"] == 1
    assert r.get("expansion_mode") == "compatibility"
    tasks = list_tasks(1)
    assert len(tasks) == 1
    assert tasks[0].forge_actions == MilestoneService.get_milestone(1).forge_actions


def test_deterministic_split_many_actions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Chunky
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | A
  - append_section requirements Overview | B
  - append_section requirements Overview | C
  - append_section requirements Overview | D
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements D
""",
    )
    r = expand_milestone_to_tasks(milestone_id=1, force=True)
    assert r["ok"]
    tasks = list_tasks(1)
    assert 2 <= len(tasks) <= 6
    assert r.get("expansion_mode") == "deterministic_multi"
    parent = MilestoneService.get_milestone(1)
    assert [a for t in tasks for a in t.forge_actions] == parent.forge_actions


def test_validate_task_list_rejects_invalid_dep_and_dup_ids():
    ok, msg = validate_task_list(
        [
            Task(
                id=1,
                milestone_id=1,
                title="First concrete slice one",
                objective="Do step one with bounded edits.",
                summary="Slice one of two.",
                depends_on=[99],
                validation="V",
                done_when="Done 1",
                forge_actions=["noop"],
                forge_validation=["file_contains requirements x"],
            ),
            Task(
                id=2,
                milestone_id=1,
                title="Second concrete slice two",
                objective="Do step two with bounded edits.",
                summary="Slice two of two.",
                depends_on=[1],
                validation="V",
                done_when="Done 2",
                forge_actions=["noop"],
                forge_validation=["file_contains requirements x"],
            ),
        ],
        require_multi=True,
    )
    assert not ok
    assert "invalid" in msg.lower()

    ok2, msg2 = validate_task_list(
        [
            Task(
                id=1,
                milestone_id=1,
                title="First concrete slice one",
                objective="O",
                summary="S",
                depends_on=[],
                validation="V",
                done_when="D",
                forge_actions=[],
                forge_validation=[],
            ),
            Task(
                id=1,
                milestone_id=1,
                title="Second concrete slice two",
                objective="O",
                summary="S",
                depends_on=[],
                validation="V",
                done_when="D",
                forge_actions=[],
                forge_validation=[],
            ),
        ],
        require_multi=True,
    )
    assert not ok2
    assert "duplicate" in msg2.lower()


def test_save_tasks_stable_serialization(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(tmp_path, "# Milestones\n")
    from forge.design_manager import Milestone

    m = Milestone(
        id=1,
        title="T: X",
        objective="Objective text here",
        scope="Scope text",
        validation="V",
        summary="",
        depends_on=[],
        forge_actions=[
            "append_section requirements Overview | z",
            "mark_milestone_completed",
        ],
        forge_validation=["file_contains requirements z"],
    )
    tasks = split_actions_into_tasks(m, 1)
    save_tasks(1, tasks)
    first = tasks_file_for_milestone(1).read_text(encoding="utf-8")
    save_tasks(1, tasks)
    second = tasks_file_for_milestone(1).read_text(encoding="utf-8")
    assert first == second
    data = json.loads(first)
    assert data["tasks"] == sorted(data["tasks"], key=lambda x: x["id"])
    canonical = json.dumps(data, indent=2, sort_keys=True)
    assert first.strip() == canonical.strip()


def test_split_actions_into_tasks_empty_returns_list():
    from forge.design_manager import Milestone

    m = Milestone(
        id=1,
        title="Empty",
        objective="O",
        scope="S",
        validation="V",
        summary="",
        depends_on=[],
        forge_actions=[],
        forge_validation=[],
    )
    assert split_actions_into_tasks(m, 1) == []


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
