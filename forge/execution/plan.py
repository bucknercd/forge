"""Build ExecutionPlan objects from parsed Milestone definitions."""

from __future__ import annotations

from forge.design_manager import Milestone
from forge.execution.models import ExecutionPlan, ForgeAction, ActionMarkMilestoneCompleted
from forge.execution.parse import parse_forge_action_line, parse_forge_validation_line
from forge.execution.validation_rules import ForgeValidationRule


class ExecutionPlanBuilder:
    @staticmethod
    def build(milestone: Milestone) -> ExecutionPlan:
        actions: list[ForgeAction] = []
        for raw in milestone.forge_actions:
            actions.append(parse_forge_action_line(raw, milestone))
        actions = ExecutionPlanBuilder._ensure_mark_completed_last(actions)
        return ExecutionPlan(milestone_id=milestone.id, actions=actions)

    @staticmethod
    def parse_validation_rules(milestone: Milestone) -> list[ForgeValidationRule]:
        rules: list[ForgeValidationRule] = []
        for raw in milestone.forge_validation:
            rules.append(parse_forge_validation_line(raw))
        return rules

    @staticmethod
    def _ensure_mark_completed_last(actions: list[ForgeAction]) -> list[ForgeAction]:
        if not any(isinstance(a, ActionMarkMilestoneCompleted) for a in actions):
            return actions
        heads = [a for a in actions if not isinstance(a, ActionMarkMilestoneCompleted)]
        tails = [a for a in actions if isinstance(a, ActionMarkMilestoneCompleted)]
        return heads + tails
