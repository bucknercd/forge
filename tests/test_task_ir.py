"""TaskIR compilation and substantiveness checks."""

from __future__ import annotations

from forge.execution.models import (
    ActionInsertAfterInFile,
    ActionMarkMilestoneCompleted,
    ActionWriteFile,
    ExecutionPlan,
)
from forge.design_manager import MilestoneService
from forge.executor import Executor
from forge.planner import Planner
from forge.reviewed_plan import save_reviewed_plan
from forge.task_ir import (
    compile_task_to_ir,
    plan_is_substantive_for_task,
    task_ir_has_minimum_behavior_depth,
)
from forge.task_service import Task, ensure_tasks_for_milestone, get_task, save_tasks
from tests.forge_test_project import configure_project


def _task(
    *,
    summary: str,
    objective: str,
    validation: str,
    forge_actions: list[str] | None = None,
    forge_validation: list[str] | None = None,
) -> Task:
    return Task(
        id=1,
        milestone_id=1,
        title="T",
        objective=objective,
        summary=summary,
        validation=validation,
        forge_actions=list(forge_actions or []),
        forge_validation=list(forge_validation or []),
    )


def test_compile_behavioral_logcheck_task_type():
    t = _task(
        summary="Build logcheck parser",
        objective="Count repeated ERROR messages, filter INFO/DEBUG, and print top 5.",
        validation="verify filtering, counting, and top-5 output",
    )
    ir = compile_task_to_ir(t)
    assert ir.task_type == "behavioral"
    assert "count" in ir.behavior_signals
    assert "filter" in ir.behavior_signals
    assert "top 5" in ir.behavior_signals


def test_compile_structural_task_type():
    t = _task(
        summary="Scaffold CLI entrypoint",
        objective="Create file skeleton and setup base module.",
        validation="file exists and imports succeed",
    )
    ir = compile_task_to_ir(t)
    assert ir.task_type == "structural"


def test_compile_doc_task_not_behavioral():
    t = _task(
        summary="Update docs and architecture decision log",
        objective="Improve README and architecture notes",
        validation="section_contains requirements Overview",
    )
    ir = compile_task_to_ir(t)
    assert ir.task_type in {"documentation", "unknown"}
    assert ir.task_type != "behavioral"


def test_compile_embedded_actions_detected_and_preserved():
    t = _task(
        summary="Do task",
        objective="Implement parser",
        validation="path_file_contains src/x.py parse",
        forge_actions=["write_file src/x.py | def parse():\\n    return []\\n"],
    )
    ir = compile_task_to_ir(t)
    assert ir.has_embedded_actions is True
    assert ir.embedded_actions
    assert ir.source_metadata.get("embedded_action_count") == 1


def test_behavior_signals_extracted_from_fields():
    t = _task(
        summary="Transform and aggregate logs",
        objective="Parse lines, group and sort counts.",
        validation="rank top 5 outputs",
    )
    ir = compile_task_to_ir(t)
    assert {"transform", "aggregate", "parse", "group", "sort", "rank", "top 5"} & set(
        ir.behavior_signals
    )


def test_compile_task_ir_preserves_behavior_from_milestone_context():
    t = _task(
        summary="Generate sample file",
        objective="Create sample data file.",
        validation="file exists",
    )
    t.milestone_context = (
        "objective: Parse logs and count repeated ERROR lines; ignore INFO/DEBUG.\n"
        "validation: top 5 frequent results\n"
    )
    ir = compile_task_to_ir(t)
    assert ir.task_type == "behavioral"
    assert "count" in ir.behavior_signals
    assert "filter" in ir.behavior_signals or "ignore" in ir.behavior_signals


def test_behavioral_task_requires_minimum_depth_signals():
    shallow = _task(
        summary="Filter log lines",
        objective="Read and filter INFO/DEBUG lines from logs.",
        validation="filtered lines are returned",
    )
    deep = _task(
        summary="Count repeated errors",
        objective="Parse logs and count repeated ERROR lines; output top 5.",
        validation="verify aggregation and top-k results",
    )
    ir_shallow = compile_task_to_ir(shallow)
    ir_deep = compile_task_to_ir(deep)
    assert ir_shallow.task_type == "behavioral"
    assert task_ir_has_minimum_behavior_depth(ir_shallow) is False
    assert task_ir_has_minimum_behavior_depth(ir_deep) is True


def test_behavioral_task_mark_only_plan_non_substantive():
    t = _task(
        summary="logcheck",
        objective="count and filter errors",
        validation="verify counting",
    )
    ir = compile_task_to_ir(t)
    plan = ExecutionPlan(milestone_id=1, actions=[ActionMarkMilestoneCompleted()])
    assert plan_is_substantive_for_task(ir, plan) is False


def test_behavioral_task_write_file_substantive():
    t = _task(
        summary="logcheck",
        objective="count and filter errors",
        validation="verify counting",
    )
    ir = compile_task_to_ir(t)
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile("src/logcheck.py", "def count_errors():\n    return 1\n")],
    )
    assert plan_is_substantive_for_task(ir, plan) is True


def test_behavioral_task_tests_only_not_substantive_for_early_tasks():
    t = _task(
        summary="logcheck",
        objective="count and filter errors",
        validation="verify counting",
    )
    ir = compile_task_to_ir(t)
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[
            ActionWriteFile(
                "tests/test_logcheck.py",
                "def test_behavior():\n    assert True\n",
            )
        ],
    )
    assert plan_is_substantive_for_task(ir, plan) is False


def test_structural_task_threshold_explicit():
    t = _task(
        summary="Scaffold module",
        objective="Create baseline structure",
        validation="file exists",
    )
    ir = compile_task_to_ir(t)
    plan = ExecutionPlan(milestone_id=1, actions=[ActionMarkMilestoneCompleted()])
    assert plan_is_substantive_for_task(ir, plan) is True


def test_behavioral_task_edit_action_substantive():
    t = _task(
        summary="logcheck",
        objective="count and filter errors",
        validation="verify counting",
    )
    ir = compile_task_to_ir(t)
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[
            ActionInsertAfterInFile(
                rel_path="src/logcheck.py",
                anchor="def main():",
                insertion="    return 1\n",
            )
        ],
    )
    assert plan_is_substantive_for_task(ir, plan) is True


class _MarkOnlyPlanner(Planner):
    mode = "deterministic"
    stable_for_recheck = True

    def build_plan(self, milestone, *, repair_context=None) -> ExecutionPlan:
        _ = repair_context
        return ExecutionPlan(
            milestone_id=milestone.id, actions=[ActionMarkMilestoneCompleted()]
        )


class _WriteSrcPlanner(Planner):
    mode = "deterministic"
    stable_for_recheck = True

    def build_plan(self, milestone, *, repair_context=None) -> ExecutionPlan:
        _ = repair_context
        return ExecutionPlan(
            milestone_id=milestone.id,
            actions=[
                ActionWriteFile("src/logcheck.py", "def count_errors():\n    return 1\n"),
                ActionMarkMilestoneCompleted(),
            ],
        )


class _WriteTestsOnlyPlanner(Planner):
    mode = "deterministic"
    stable_for_recheck = True

    def build_plan(self, milestone, *, repair_context=None) -> ExecutionPlan:
        _ = repair_context
        return ExecutionPlan(
            milestone_id=milestone.id,
            actions=[
                ActionWriteFile(
                    "tests/test_logcheck.py", "def test_behavior():\n    assert True\n"
                ),
                ActionMarkMilestoneCompleted(),
            ],
        )


def test_behavioral_preview_rejects_mark_only_plan(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: B
- **Objective**: Count ERROR lines and filter DEBUG lines.
- **Scope**: src/ and tests/.
- **Validation**: verify counting behavior.
""",
    )
    ensure_tasks_for_milestone(1)
    t = get_task(1, 1)
    assert t is not None
    # Force planner path (no embedded actions), keep behavioral objective.
    save_tasks(
        1,
        [
            Task(
                id=t.id,
                milestone_id=t.milestone_id,
                title=t.title,
                objective=t.objective,
                summary=t.summary,
                depends_on=list(t.depends_on),
                files_allowed=t.files_allowed,
                validation=t.validation,
                done_when=t.done_when,
                status=t.status,
                forge_actions=[],
                forge_validation=list(t.forge_validation),
            )
        ],
    )
    out = Executor.preview_milestone(1, planner=_MarkOnlyPlanner(), task_id=1)
    assert out["ok"] is False
    assert out.get("failure_type") == "non_substantive_behavioral_plan"


def test_behavioral_preview_enriches_under_scoped_filter_only_task(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: B
- **Objective**: Parse logs, count repeated ERROR lines, and output top 5.
- **Scope**: src/ and tests/.
- **Validation**: verify counting and top-k behavior.
""",
    )
    ensure_tasks_for_milestone(1)
    t = get_task(1, 1)
    assert t is not None
    save_tasks(
        1,
        [
            Task(
                id=t.id,
                milestone_id=t.milestone_id,
                title=t.title,
                objective="Read and filter INFO/DEBUG lines only.",
                summary="Filter-only behavior slice.",
                depends_on=list(t.depends_on),
                files_allowed=t.files_allowed,
                validation=t.validation,
                done_when=t.done_when,
                status=t.status,
                forge_actions=[],
                forge_validation=list(t.forge_validation),
            )
        ],
    )
    out = Executor.preview_milestone(1, planner=_WriteSrcPlanner(), task_id=1)
    assert out["ok"] is True
    em = out.get("task_behavior_enrichment") or {}
    assert em.get("enriched") is True
    t2 = get_task(1, 1)
    assert t2 is not None
    blob = f"{t2.objective} {t2.summary}".lower()
    assert "count" in blob
    assert t2.forge_actions == []


def test_behavioral_preview_accepts_src_write_plan(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: B
- **Objective**: Count and filter log errors.
- **Scope**: src/ and tests/.
- **Validation**: verify counting behavior.
""",
    )
    ensure_tasks_for_milestone(1)
    t = get_task(1, 1)
    assert t is not None
    save_tasks(
        1,
        [
            Task(
                id=t.id,
                milestone_id=t.milestone_id,
                title=t.title,
                objective=t.objective,
                summary=t.summary,
                depends_on=list(t.depends_on),
                files_allowed=t.files_allowed,
                validation=t.validation,
                done_when=t.done_when,
                status=t.status,
                forge_actions=[],
                forge_validation=list(t.forge_validation),
            )
        ],
    )
    out = Executor.preview_milestone(1, planner=_WriteSrcPlanner(), task_id=1)
    assert out["ok"] is True


def test_behavioral_preview_rejects_tests_only_plan_for_task1(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: B
- **Objective**: Parse and count errors.
- **Scope**: src/ and tests/.
- **Validation**: verify top 5 ranking behavior.
""",
    )
    ensure_tasks_for_milestone(1)
    t = get_task(1, 1)
    assert t is not None
    save_tasks(
        1,
        [
            Task(
                id=t.id,
                milestone_id=t.milestone_id,
                title=t.title,
                objective=t.objective,
                summary=t.summary,
                depends_on=list(t.depends_on),
                files_allowed=t.files_allowed,
                validation=t.validation,
                done_when=t.done_when,
                status=t.status,
                forge_actions=[],
                forge_validation=list(t.forge_validation),
            )
        ],
    )
    out = Executor.preview_milestone(1, planner=_WriteTestsOnlyPlanner(), task_id=1)
    assert out["ok"] is False
    assert out.get("failure_type") == "non_substantive_behavioral_plan"


def test_structural_preview_allows_mark_only_plan(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: S
- **Objective**: Scaffold entrypoint and setup base files.
- **Scope**: structural setup only.
- **Validation**: file exists.
""",
    )
    ensure_tasks_for_milestone(1)
    t = get_task(1, 1)
    assert t is not None
    save_tasks(
        1,
        [
            Task(
                id=t.id,
                milestone_id=t.milestone_id,
                title=t.title,
                objective=t.objective,
                summary=t.summary,
                depends_on=list(t.depends_on),
                files_allowed=t.files_allowed,
                validation=t.validation,
                done_when=t.done_when,
                status=t.status,
                forge_actions=[],
                forge_validation=list(t.forge_validation),
            )
        ],
    )
    out = Executor.preview_milestone(1, planner=_MarkOnlyPlanner(), task_id=1)
    assert out["ok"] is True


def test_apply_reviewed_plan_rejects_non_substantive_behavioral_plan(
    tmp_path, monkeypatch
):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: B
- **Objective**: Count and filter errors.
- **Scope**: src/ and tests/.
- **Validation**: verify counting.
- **Forge Actions**:
  - write_file src/logcheck.py | def count_errors():\\n    return 1\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/logcheck.py count_errors
""",
    )
    ensure_tasks_for_milestone(1)
    t = get_task(1, 1)
    assert t is not None
    save_tasks(
        1,
        [
            Task(
                id=t.id,
                milestone_id=t.milestone_id,
                title=t.title,
                objective="Count and filter ERROR entries.",
                summary="Behavior-heavy logcheck task",
                depends_on=list(t.depends_on),
                files_allowed=t.files_allowed,
                validation="verify count/filter behavior",
                done_when=t.done_when,
                status=t.status,
                forge_actions=[],
                forge_validation=[],
            )
        ],
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    plan = ExecutionPlan(milestone_id=1, actions=[ActionMarkMilestoneCompleted()])
    payload = save_reviewed_plan(
        1,
        milestone.title,
        plan,
        planner_mode="llm",
        planner_metadata={"mode": "llm", "is_nondeterministic": True},
        task_id=1,
    )
    monkeypatch.setattr("forge.executor.validate_reviewed_plan", lambda *_a, **_k: (True, ""))
    out = Executor.apply_reviewed_plan(payload["plan_id"])
    assert out["ok"] is False
    assert out.get("failure_type") == "non_substantive_behavioral_plan"
