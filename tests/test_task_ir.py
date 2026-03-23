"""TaskIR compilation and substantiveness checks."""

from __future__ import annotations

from forge.execution.models import (
    ActionMarkMilestoneCompleted,
    ActionWriteFile,
    ExecutionPlan,
)
from forge.task_ir import compile_task_to_ir, plan_is_substantive_for_task
from forge.task_service import Task


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


def test_structural_task_threshold_explicit():
    t = _task(
        summary="Scaffold module",
        objective="Create baseline structure",
        validation="file exists",
    )
    ir = compile_task_to_ir(t)
    plan = ExecutionPlan(milestone_id=1, actions=[ActionMarkMilestoneCompleted()])
    assert plan_is_substantive_for_task(ir, plan) is False
