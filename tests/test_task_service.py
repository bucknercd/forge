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


def test_llm_task_expansion_strips_pseudo_actions_and_invokes_planner(tmp_path, monkeypatch):
    """Regression: LLM task expansion must not persist pseudo-embedded actions.

    Specifically, task expansion must not write invalid pseudo-actions such as
    create_file/modify_file into `.system/tasks/*.json` (planner parsing must
    never see them).
    """
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Spec only
- **Objective**: Implement logcheck behavior (count/filter ERROR lines).
- **Scope**: src/ and tests/
- **Validation**: behavioral correctness checks
""",
    )
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "openai"}}, indent=2),
        encoding="utf-8",
    )

    class _BadTaskExpansionLLM:
        def generate(self, prompt: str) -> str:  # noqa: ARG002
            payload = {
                "tasks": [
                    {
                        "id": 1,
                        "title": "Behavior slice one for logcheck tool",
                        "objective": "Filter and count repeated ERROR lines.",
                        "summary": "Slice one of two behavior work items.",
                        "depends_on": [],
                        "validation": "file_contains requirements Overview",
                        "done_when": "Slice one validation passes.",
                        "forge_actions": ["create_file examples/sample.log", "mark_milestone_completed"],
                        "forge_validation": ["file_contains requirements Overview"],
                    },
                    {
                        "id": 2,
                        "title": "Behavior slice two for logcheck tool",
                        "objective": "Output top-k frequent ERROR lines.",
                        "summary": "Slice two of two behavior work items.",
                        "depends_on": [1],
                        "validation": "file_contains requirements Overview",
                        "done_when": "Slice two validation passes.",
                        "forge_actions": ["modify_file examples/sample.log", "mark_milestone_completed"],
                        "forge_validation": ["file_contains requirements Overview"],
                    },
                ]
            }
            return json.dumps(payload)

        @property
        def client_id(self) -> str:  # noqa: D401
            return "bad_task_expander"

    # Ensure task_service uses our bad task expander for LLM expansion.
    monkeypatch.setattr(
        "forge.task_service.resolve_llm_client_from_policy",
        lambda _policy: (_BadTaskExpansionLLM(), None),
    )

    r = expand_milestone_to_tasks(milestone_id=1, force=True)
    assert r["ok"] is True

    tasks = list_tasks(1)
    assert tasks, "expected task file to be written"
    # LLM-expanded tasks must be spec-only: no embedded forge_actions.
    assert all(t.forge_actions == [] for t in tasks)

    raw_tasks_json = tasks_file_for_milestone(1).read_text(encoding="utf-8")
    assert "create_file" not in raw_tasks_json
    assert "modify_file" not in raw_tasks_json

    # Since tasks have no embedded actions, the planner must be invoked for preview.
    from forge.planner import LLMPlanner
    from tests.test_planner_abstraction import CapturingLLM

    capture = CapturingLLM(
        json.dumps(
            {
                "actions": [
                    "write_file src/logcheck.py | def main():\\n    return 'ok'\\n",
                    "mark_milestone_completed",
                ]
            }
        )
    )
    planner = LLMPlanner(capture, fallback_to_milestone_actions=False)
    preview = Executor.preview_milestone(1, planner=planner, task_id=tasks[0].id)
    assert preview["ok"] is True
    assert capture.last_prompt != ""


def test_behavior_heavy_llm_decomposition_rejects_setup_only_first_task(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Logcheck behavior
- **Objective**: Parse logs, count repeated ERROR lines, ignore INFO/DEBUG, and output top 5.
- **Scope**: src/ and tests/
- **Validation**: verify filtering, counting, and top-k behavior
""",
    )
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "openai"}}, indent=2),
        encoding="utf-8",
    )

    class _ShallowLLM:
        def generate(self, prompt: str) -> str:  # noqa: ARG002
            return json.dumps(
                {
                    "tasks": [
                        {
                            "id": 1,
                            "title": "Generate sample log file",
                            "objective": "Create examples/sample_log.txt.",
                            "summary": "Sample data setup only.",
                            "depends_on": [],
                            "validation": "file exists",
                            "done_when": "sample file created",
                            "forge_actions": [],
                            "forge_validation": [],
                        },
                        {
                            "id": 2,
                            "title": "Add tests",
                            "objective": "Add tests file",
                            "summary": "testing setup",
                            "depends_on": [1],
                            "validation": "pytest -q",
                            "done_when": "tests added",
                            "forge_actions": [],
                            "forge_validation": [],
                        },
                    ]
                }
            )

    monkeypatch.setattr(
        "forge.task_service.resolve_llm_client_from_policy",
        lambda _policy: (_ShallowLLM(), None),
    )

    r = expand_milestone_to_tasks(milestone_id=1, force=True)
    assert r["ok"] is True
    # setup-only llm decomposition should be rejected and fall back.
    assert r.get("expansion_mode") != "llm_multi"
    tasks = list_tasks(1)
    assert tasks
    first_blob = f"{tasks[0].objective} {tasks[0].summary}".lower()
    assert "count" in first_blob or "parse" in first_blob or "error" in first_blob


def test_behavior_heavy_llm_decomposition_rejects_filter_only_first_task(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Logcheck behavior
- **Objective**: Parse logs, count repeated ERROR lines, ignore INFO/DEBUG, and output top 5.
- **Scope**: src/ and tests/
- **Validation**: verify filtering, counting, aggregation, and top-k behavior
""",
    )
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "openai"}}, indent=2),
        encoding="utf-8",
    )

    class _FilterOnlyFirstTaskLLM:
        def generate(self, prompt: str) -> str:  # noqa: ARG002
            return json.dumps(
                {
                    "tasks": [
                        {
                            "id": 1,
                            "title": "Read and filter log lines",
                            "objective": "Read log file and filter out INFO/DEBUG lines.",
                            "summary": "Initial parse + filter slice.",
                            "depends_on": [],
                            "validation": "filtering works",
                            "done_when": "filtered lines returned",
                            "forge_actions": [],
                            "forge_validation": [],
                        },
                        {
                            "id": 2,
                            "title": "Count repeated ERROR lines",
                            "objective": "Aggregate repeated ERROR messages and produce top 5.",
                            "summary": "Add counting and top-k behavior.",
                            "depends_on": [1],
                            "validation": "counting works",
                            "done_when": "top 5 output rendered",
                            "forge_actions": [],
                            "forge_validation": [],
                        },
                    ]
                }
            )

    monkeypatch.setattr(
        "forge.task_service.resolve_llm_client_from_policy",
        lambda _policy: (_FilterOnlyFirstTaskLLM(), None),
    )

    r = expand_milestone_to_tasks(milestone_id=1, force=True)
    assert r["ok"] is True
    # filter-only first task must be rejected for behavior-heavy milestones.
    assert r.get("expansion_mode") != "llm_multi"
    tasks = list_tasks(1)
    assert tasks
    first_blob = f"{tasks[0].objective} {tasks[0].summary}".lower()
    assert (
        "count" in first_blob
        or "aggregate" in first_blob
        or "top 5" in first_blob
        or "top-k" in first_blob
    )


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
