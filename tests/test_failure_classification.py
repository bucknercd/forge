"""Unit tests for repair failure classification."""

from __future__ import annotations

from forge.failure_classification import (
    FailureClassification,
    classify_repair_failure,
    detect_identical_repair_plan,
)
from forge.repair_prompts import repair_mode_prompt_block
from forge.task_feedback import build_repair_context, repair_context_to_prompt_appendix


def test_classify_syntax_from_apply_errors():
    fc = classify_repair_failure(
        phase="apply",
        apply_errors=["SyntaxError: invalid syntax (x.py, line 2)"],
        attempt=1,
    )
    assert fc.mode == "syntax_fix"
    assert fc.phase == "apply"


def test_classify_format_from_json_planner_error():
    fc = classify_repair_failure(
        phase="apply",
        apply_errors=["LLM planner: JSON extraction failed: Could not extract"],
        attempt=1,
    )
    assert fc.mode == "format_fix"


def test_classify_behavior_from_pytest_output():
    gates = [
        {
            "name": "repo_test_command",
            "ok": False,
            "message": "exit 1",
            "details": {"output": "E   AssertionError: expected 1 got 2\n", "command": "pytest"},
        }
    ]
    fc = classify_repair_failure(phase="gates", gate_results=gates, attempt=1)
    assert fc.mode == "behavior_fix"


def test_classify_missing_impl_stub():
    gates = [
        {
            "name": "repo_test_command",
            "ok": False,
            "message": "exit 1",
            "details": {"output": "NotImplementedError: todo\n"},
        }
    ]
    fc = classify_repair_failure(phase="gates", gate_results=gates, attempt=1)
    assert fc.mode == "missing_impl"


def test_classify_validation_bug_diag():
    gates = [
        {
            "name": "milestone_validation",
            "ok": False,
            "message": "path_file_contains failed: x missing substring 'y' (unquote_applied=yes)",
            "details": {},
        }
    ]
    fc = classify_repair_failure(phase="gates", gate_results=gates, attempt=1)
    assert fc.mode == "validation_bug"


def test_no_op_identical_plan_after_apply_failure_only():
    h = "abcd" * 16
    assert not detect_identical_repair_plan(
        attempt=1, previous_plan_hash=None, current_plan_hash=h
    )
    assert detect_identical_repair_plan(
        attempt=2, previous_plan_hash=h, current_plan_hash=h
    )


def test_classify_no_op_when_hashes_match_and_attempt_gt_1():
    h = "a" * 64
    fc = classify_repair_failure(
        phase="apply",
        apply_errors=[],
        attempt=2,
        previous_plan_hash=h,
        current_plan_hash=h,
    )
    assert fc.mode == "no_op_repair"


def test_repair_prompt_appendix_includes_mode_block():
    fc = FailureClassification(
        "syntax_fix",
        "gates",
        ("test",),
        {},
    )
    ctx = build_repair_context(
        1,
        1,
        1,
        apply_ok=True,
        gate_results=[],
        classification=fc.to_dict(),
        repair_mode=fc.mode,
    )
    text = repair_context_to_prompt_appendix(ctx)
    assert "REPAIR MODE: syntax_fix" in text
    assert "classifier mode=" in text


def test_repair_mode_prompt_block_unknown():
    fc = FailureClassification("unknown_failure", "apply", (), {})
    block = repair_mode_prompt_block(fc)
    assert "unknown_failure" in block
