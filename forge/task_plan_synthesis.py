"""
Deterministic execution-plan synthesis from task JSON ``forge_actions``.

Used at the planner-ingestion boundary: when ``.system/tasks/m*.json`` already
contains non-empty, parseable action lines, Forge can build a reviewed plan
without invoking an LLM planner.
"""

from __future__ import annotations

from forge.design_manager import Milestone
from forge.execution.models import ExecutionPlan, ForgeAction
from forge.execution.parse import parse_forge_action_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.planner_normalize import normalize_llm_planner_action_line
from forge.task_service import Task


class TaskEmbeddedActionsError(ValueError):
    """Embedded ``forge_actions`` failed canonical parse (or boundary normalize)."""

    def __init__(
        self,
        message: str,
        *,
        task_id: int,
        offending_action: str | None = None,
        parser_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.task_id = task_id
        self.offending_action = offending_action
        self.parser_message = parser_message or message


def task_has_nonempty_embedded_forge_actions(task: Task) -> bool:
    """True when the task lists at least one non-whitespace forge action line."""
    return any(str(a).strip() for a in (task.forge_actions or []))


def synthesize_execution_plan_from_task(
    task: Task, milestone: Milestone
) -> tuple[ExecutionPlan, dict[str, object]]:
    """
    Parse each task action line (with the same planner boundary normalization as
    :class:`~forge.planner.LLMPlanner`), build an :class:`ExecutionPlan`, and
    validate milestone validation rules parse.

    Returns ``(plan, planner_metadata)`` for persistence alongside reviewed plans.
    """
    normalization_notes: list[str] = []
    normalization_events: list[dict[str, str]] = []

    actions: list[ForgeAction] = []
    source = milestone.forge_actions_with_lines or [(0, raw) for raw in milestone.forge_actions]

    for idx, (line_no, raw) in enumerate(source, start=1):
        if not str(raw).strip():
            continue
        try:
            normalized, notes = normalize_llm_planner_action_line(raw)
        except ValueError as exc:
            raise TaskEmbeddedActionsError(
                f"Task {task.id} forge_actions normalize error: {exc}",
                task_id=task.id,
                offending_action=raw,
                parser_message=str(exc),
            ) from exc

        for n in notes:
            normalization_notes.append(f"action {idx}: {n}")
        if normalized != raw:
            normalization_events.append(
                {
                    "action_index": str(idx),
                    "original_action": raw,
                    "normalized_action": normalized,
                    "reason": (notes[0] if notes else "normalized at task-ingestion boundary"),
                }
            )

        try:
            actions.append(
                parse_forge_action_line(
                    normalized, milestone, line_no=line_no if line_no else None
                )
            )
        except ValueError as exc:
            raise TaskEmbeddedActionsError(
                f"Task {task.id} forge_actions parse error: {exc}",
                task_id=task.id,
                offending_action=raw,
                parser_message=str(exc),
            ) from exc

    if not actions:
        raise TaskEmbeddedActionsError(
            f"Task {task.id} has no non-empty parseable forge_actions lines.",
            task_id=task.id,
            offending_action=None,
            parser_message="empty_embedded_forge_actions",
        )

    actions = ExecutionPlanBuilder._ensure_mark_completed_last(actions)
    plan = ExecutionPlan(milestone_id=milestone.id, actions=actions)

    try:
        ExecutionPlanBuilder.parse_validation_rules(milestone)
    except ValueError as exc:
        raise TaskEmbeddedActionsError(
            f"Task {task.id} forge_validation parse error: {exc}",
            task_id=task.id,
            offending_action=None,
            parser_message=str(exc),
        ) from exc

    meta: dict[str, object] = {
        "is_nondeterministic": False,
        "llm_client": None,
        "llm_model": None,
        "plan_source": "task_forge_actions",
        "plan_synthesis": "embedded_task_actions",
        "reason": "embedded_forge_actions_present",
    }
    if normalization_notes:
        meta["normalization_notes"] = normalization_notes
    if normalization_events:
        meta["normalization_events"] = normalization_events

    return plan, meta
