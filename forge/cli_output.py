"""Stable machine-readable output serializers for CLI commands."""

from __future__ import annotations

from typing import Any


def serialize_lint_result(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize lint payload into a stable schema for automation.
    Expects keys: ok, command, selected_milestone_id, checked, total_errors, milestones, message?
    """
    return {
        "command": "milestone-lint",
        "ok": bool(payload.get("ok", False)),
        "selected_milestone_id": payload.get("selected_milestone_id"),
        "checked_milestones": int(payload.get("checked", 0)),
        "total_errors": int(payload.get("total_errors", 0)),
        "milestones": payload.get("milestones", []),
        "message": payload.get("message", ""),
    }


def serialize_preview_result(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize preview payload into a stable schema for automation.
    Expects executor preview result fields.
    """
    return {
        "command": "milestone-preview",
        "ok": bool(payload.get("ok", False)),
        "plan_id": payload.get("plan_id"),
        "plan_file": payload.get("plan_file"),
        "planner_mode": payload.get("planner_mode", "deterministic"),
        "planner_metadata": payload.get("planner_metadata", {}),
        "review_enforcement": payload.get("review_enforcement", {}),
        "milestone_id": payload.get("milestone_id"),
        "task_id": payload.get("task_id"),
        "requires_task_selection": bool(payload.get("requires_task_selection", False)),
        "tasks": payload.get("tasks"),
        "title": payload.get("title"),
        "message": payload.get("message", ""),
        "artifact_summary": payload.get("artifact_summary", ""),
        "targeted_artifacts": payload.get("files_changed", []),
        "planned_actions": payload.get("execution_plan", {}).get("actions", []),
        "actions_applied": payload.get("actions_applied", []),
        "warnings": payload.get("warnings", []),
        "errors": list(payload.get("errors", [])),
        "summary_counts": _summary_counts(payload.get("actions_applied", [])),
    }


def serialize_apply_plan_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": "milestone-apply-plan",
        "ok": bool(payload.get("ok", False)),
        "apply_ok": bool(payload.get("apply_ok", payload.get("ok", False))),
        "gates_ok": bool(payload.get("gates_ok", True)),
        "plan_id": payload.get("plan_id"),
        "planner_mode": payload.get("planner_mode", "deterministic"),
        "planner_metadata": payload.get("planner_metadata", {}),
        "review_enforcement": payload.get("review_enforcement", {}),
        "milestone_id": payload.get("milestone_id"),
        "task_id": payload.get("task_id"),
        "title": payload.get("title"),
        "message": payload.get("message", ""),
        "artifact_summary": payload.get("artifact_summary", ""),
        "gate_summary": payload.get("gate_summary", ""),
        "gate_results": payload.get("gate_results", []),
        "policy": payload.get("policy", {}),
        "result_artifact": payload.get("result_artifact"),
        "targeted_artifacts": payload.get("files_changed", []),
        "actions_applied": payload.get("actions_applied", []),
        "warnings": payload.get("warnings", []),
        "errors": payload.get("errors", []),
        "summary_counts": _summary_counts(payload.get("actions_applied", [])),
    }


def _summary_counts(actions_applied: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"changed": 0, "skipped": 0, "failed": 0}
    for action in actions_applied:
        outcome = action.get("outcome")
        if outcome in counts:
            counts[outcome] += 1
    return counts
