"""Build ExecutionPlan objects from parsed Milestone definitions."""

from __future__ import annotations

import logging

from forge.design_manager import Milestone
from forge.execution.models import ExecutionPlan, ForgeAction, ActionMarkMilestoneCompleted
from forge.execution.parse import parse_forge_action_line, parse_forge_validation_line
from forge.execution.validation_rules import ForgeValidationRule
from forge.validation_normalize import normalize_validation_rule

logger = logging.getLogger(__name__)


class ExecutionPlanBuilder:
    @staticmethod
    def build(milestone: Milestone) -> ExecutionPlan:
        actions: list[ForgeAction] = []
        source = milestone.forge_actions_with_lines or [(0, raw) for raw in milestone.forge_actions]
        for line_no, raw in source:
            try:
                actions.append(parse_forge_action_line(raw, milestone, line_no=line_no or None))
            except ValueError as exc:
                raise ValueError(
                    f"Milestone {milestone.id} action parse error: {exc}"
                ) from exc
        actions = ExecutionPlanBuilder._ensure_mark_completed_last(actions)
        return ExecutionPlan(milestone_id=milestone.id, actions=actions)

    @staticmethod
    def parse_validation_rules(milestone: Milestone) -> list[ForgeValidationRule]:
        rules: list[ForgeValidationRule] = []
        source = milestone.forge_validation_with_lines or [
            (0, raw) for raw in milestone.forge_validation
        ]
        for line_no, raw in source:
            normalized = normalize_validation_rule(raw)
            if normalized is None:
                logger.warning("Dropped invalid validation: %r", raw)
                continue
            if normalized != raw:
                logger.warning("Normalized validation: %r -> %r", raw, normalized)
            try:
                rules.append(parse_forge_validation_line(normalized, line_no=line_no or None))
            except ValueError as exc:
                raise ValueError(
                    f"Milestone {milestone.id} validation parse error: {exc}"
                ) from exc
        return rules

    @staticmethod
    def _ensure_mark_completed_last(actions: list[ForgeAction]) -> list[ForgeAction]:
        if not any(isinstance(a, ActionMarkMilestoneCompleted) for a in actions):
            return actions
        heads = [a for a in actions if not isinstance(a, ActionMarkMilestoneCompleted)]
        tails = [a for a in actions if isinstance(a, ActionMarkMilestoneCompleted)]
        return heads + tails
